"""Presentation preferences, exact UI translations and semantic color palettes."""
from __future__ import annotations
import json,re
from pathlib import Path
from string import Formatter

UI_DEFAULTS={'ui_language':'pt-BR','ui_theme':'dark'}
LANGUAGES=('pt-BR','en','es')
THEMES=('dark','light')
COLORS={
 'dark':dict(bg='#101216',rail='#0c0e11',card='#171a20',elevated='#1d2129',line='#2b3039',text='#eeeae4',muted='#a0a7b3',accent='#a78bfa',accentHover='#bba5ff',accentText='#191326',green='#59d6a0',red='#ff777b',hover='#292e38',navHover='#15181d',navIndex='#636c7a',caption='#69717f',disabledText='#737985',disabledBg='#20232a',dangerBorder='#66373b',optionHover='#343a46',switchBorder='#59616f',switchThumb='#b1b8c3',queueBg='#111419',resultBg='#12151a',consoleBg='#0c0f13',consoleText='#b6c1cd',previewText='#c6ccd5',heroStart='#262027',heroEnd='#171c25',heroBorder='#3c334e',heroGlyph='#252d38',heroLine='#42404a',heroText='#b1adb5',successBg='#18221f',successBorder='#2c433a',successText='#b6d0c3',toastBg='#2b3039',toastBorder='#4b5361'),
 'light':dict(bg='#f4f3f8',rail='#ebe9f2',card='#ffffff',elevated='#eeecf5',line='#d2cedf',text='#211d2c',muted='#615c70',accent='#6845bf',accentHover='#5835ab',accentText='#ffffff',green='#14734e',red='#b32638',hover='#e0dbea',navHover='#e2deec',navIndex='#716a82',caption='#686077',disabledText='#817b8e',disabledBg='#e8e5ef',dangerBorder='#d4a0a8',optionHover='#ddd5ed',switchBorder='#8c849e',switchThumb='#ffffff',queueBg='#f7f6fa',resultBg='#f7f6fa',consoleBg='#f0eef6',consoleText='#343047',previewText='#343047',heroStart='#e9dff6',heroEnd='#e5eaf6',heroBorder='#ccc1e0',heroGlyph='#d2c9e2',heroLine='#b9afca',heroText='#59516c',successBg='#e7f3ec',successBorder='#b8d8c5',successText='#24583d',toastBg='#ffffff',toastBorder='#b8aecb')}


def normalize_preferences(values):
    return {'ui_language':values.get('ui_language') if values.get('ui_language') in LANGUAGES else UI_DEFAULTS['ui_language'],
            'ui_theme':values.get('ui_theme') if values.get('ui_theme') in THEMES else UI_DEFAULTS['ui_theme']}


class Translations:
    def __init__(self):
        self.catalogs={code:json.loads((Path(__file__).parent/'locales'/(code+'.json')).read_text(encoding='utf-8')) for code in ('en','es')}
        self.patterns=[]
        for source in self.catalogs['en']:
            if '{' not in source:continue
            parts=[];names=[]
            for literal,name,_,_ in Formatter().parse(source):
                parts.append(re.escape(literal))
                if name:
                    parts.append('(?P<'+name+'>.*?)');names.append(name)
            self.patterns.append((re.compile(''.join(parts),re.S),source,names))

    def text(self,language,source,values=None):
        target=self.catalogs.get(language,{}).get(source,source)
        return target.format_map(values) if values is not None else target

    def message(self,language,text):
        if language=='pt-BR':return text
        catalog=self.catalogs.get(language,{})
        if text in catalog:return catalog[text]
        for pattern,source,names in self.patterns:
            match=pattern.fullmatch(text)
            if match:
                values=match.groupdict()
                if 'stage' in values:values['stage']=self.message(language,values['stage'])
                return self.text(language,source,values)
        # Filenames, paths, model identifiers and diagnostic details are data.
        # Only translate known UI segments, never replace words inside a name.
        if ' · ' in text:
            return ' · '.join(self.message(language,part) for part in text.split(' · '))
        return text
