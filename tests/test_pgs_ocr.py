import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from pgs_ocr import BitmapCue,segments,text_lines,timestamp,convert
from speech_context import read_context

class PgsTests(unittest.TestCase):
    def test_segments_and_truncated_payload(self):
        self.assertEqual(list(segments(bytes([20,0,2,3,4]))),[(20,bytes([3,4]))])
        with self.assertRaises(ValueError):list(segments(bytes([20,0,3,1])))
    def test_line_segmentation_keeps_two_speakers(self):
        image=np.full((30,100),255,dtype=np.uint8);image[2:10,5:80]=0;image[20:28,5:80]=0
        self.assertEqual(len(text_lines(image)),2)
    def test_timestamp_rounding(self):
        self.assertEqual(timestamp(3599.9996),'01:00:00,000')
    def test_conversion_preserves_uncertainty_origin_and_existing_output(self):
        class Reader:
            def recognize(self,image):return dict(text='Hello',min_score=.8,alternate='Hallo',flags=['ocr_disagreement'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root=Path(name);source=root/'original.sup';source.write_bytes(b'original')
            cue=BitmapCue(1,2,np.zeros((4,4),dtype=np.uint8))
            with patch('pgs_ocr.read_pgs',return_value=iter([cue])):first=convert(source,root,Reader())
            with patch('pgs_ocr.read_pgs',return_value=iter([cue])):second=convert(source,root,Reader())
            self.assertNotEqual(first,second);self.assertEqual(source.read_bytes(),b'original')
            context=read_context(first);self.assertEqual(context['source_kind'],'ocr')
            self.assertEqual(context['uncertain_ranges'][0]['start'],1)
            first.write_text('changed',encoding='utf-8');self.assertEqual(read_context(first),{})
    def test_empty_ocr_never_publishes_incomplete_srt(self):
        class Reader:
            def recognize(self,image):return dict(text='',flags=['empty_ocr'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root=Path(name);source=root/'original.sup';source.write_bytes(b'original')
            with patch('pgs_ocr.read_pgs',return_value=iter([BitmapCue(1,2,None)])):
                with self.assertRaises(ValueError):convert(source,root,Reader())
            self.assertFalse(list(root.glob('*.srt')))


    def test_pgs_clear_event_and_multiple_rectangles(self):
        from types import SimpleNamespace
        from pgs_ocr import read_pgs
        def segment(kind,payload):return bytes([kind])+len(payload).to_bytes(2,'big')+payload
        pcs=bytes(10)+bytes([2])
        palette=bytes([0,0,1,235,128,128,255])
        rect=lambda x:SimpleNamespace(x=x,y=0,width=2,height=4,planes=[bytes([1]*8)])
        class Packet:
            time_base=1
            def __init__(self,t,data,rectangles=()):self.pts=t;self.data=data;self.size=len(data);self.rectangles=rectangles
            def __bytes__(self):return self.data
            def decode(self):return self.rectangles
        packets=[Packet(1,segment(0x16,pcs)),Packet(1,segment(0x14,palette)),Packet(1,segment(0x80,b''),[rect(0),rect(5)]),Packet(3,segment(0x16,bytes(11)))]
        class Container:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def demux(self):return iter(packets)
        with patch('av.open',return_value=Container()):cues=list(read_pgs('fake.sup'))
        self.assertEqual(len(cues),1);self.assertEqual((cues[0].start,cues[0].end),(1,3))
        self.assertEqual(cues[0].image.shape,(4,7))
        self.assertTrue(np.all(cues[0].image[:,2:5]==255))
        packets.pop()
        with patch('av.open',return_value=Container()):
            with self.assertRaises(ValueError):list(read_pgs('fake.sup'))
