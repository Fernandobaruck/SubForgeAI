using System;
using System.IO;
using System.Net;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Concurrent;

// Native streaming avoids running PowerShell code for every network buffer.
// Each part retains a contiguous prefix, compatible with the original installer.
public sealed class SubForgeDownloadSession : IDisposable {
    private readonly string[] urls, paths;
    private readonly long[] sizes;
    private readonly int connections;
    private readonly CancellationTokenSource cancellation = new CancellationTokenSource();
    private readonly ConcurrentDictionary<int, HttpWebRequest> requests = new ConcurrentDictionary<int, HttpWebRequest>();
    private Task job;
    private long completed;
    public long Total { get; private set; }
    public long Initial { get; private set; }
    public long Completed { get { return Interlocked.Read(ref completed); } }
    public bool IsCompleted { get { return job.IsCompleted; } }

    private SubForgeDownloadSession(string[] u, string[] p, long[] s, int n) {
        if (u.Length != p.Length || p.Length != s.Length || n < 1 || n > 8) throw new ArgumentException("Invalid download plan");
        urls=u; paths=p; sizes=s; connections=n;
        for(int i=0;i<paths.Length;i++) {
            if(sizes[i]<=0) throw new ArgumentException("Invalid part size");
            long length=File.Exists(paths[i]) ? new FileInfo(paths[i]).Length : 0;
            if(length>sizes[i]) throw new IOException("Arquivo parcial maior que o esperado: "+paths[i]);
            Initial+=length; Total+=sizes[i];
        }
        completed=Initial;
    }
    public static SubForgeDownloadSession Start(string[] urls, string[] paths, long[] sizes, int connections) {
        var session=new SubForgeDownloadSession(urls,paths,sizes,connections);
        session.job=Task.Factory.StartNew(session.Run);
        return session;
    }
    private void Run() {
        try {
            Parallel.For(0, paths.Length, new ParallelOptions {MaxDegreeOfParallelism=connections,CancellationToken=cancellation.Token}, Download);
        } catch {
            Cancel();
            throw;
        }
    }
    private void Download(int index) {
        for(int attempt=0;attempt<3;attempt++) {
            cancellation.Token.ThrowIfCancellationRequested();
            long offset=File.Exists(paths[index]) ? new FileInfo(paths[index]).Length : 0;
            if(offset==sizes[index]) return;
            if(offset>sizes[index]) throw new IOException("Arquivo parcial inválido: "+paths[index]);
            HttpWebRequest request=null;
            try {
                request=(HttpWebRequest)WebRequest.Create(urls[index]);
                request.UserAgent="SubForgeAI-installer-fast";
                request.Timeout=30000;request.ReadWriteTimeout=30000;
                request.ServicePoint.ConnectionLimit=Math.Max(8,connections);
                request.AllowAutoRedirect=true;
                if(offset>0)request.AddRange(offset);
                requests[index]=request;
                using(var response=(HttpWebResponse)request.GetResponse()) {
                    if(offset>0 && response.StatusCode==HttpStatusCode.PartialContent) {
                        string range=response.Headers["Content-Range"];
                        string expected="bytes "+offset+"-"+(sizes[index]-1)+"/"+sizes[index];
                        if(range!=expected)throw new IOException("Resposta de retomada inválida: "+range);
                    } else if(response.StatusCode==HttpStatusCode.OK) {
                        if(offset>0) {Interlocked.Add(ref completed,-offset);offset=0;}
                    } else throw new IOException("Resposta HTTP inesperada: "+response.StatusCode);
                    if(response.ContentLength>=0 && response.ContentLength!=sizes[index]-offset)
                        throw new IOException("Tamanho HTTP diferente do manifesto assinado.");
                    using(var input=response.GetResponseStream())
                    using(var output=new FileStream(paths[index],offset==0 ? FileMode.Create : FileMode.Append,FileAccess.Write,FileShare.Read,1048576)) {
                        var buffer=new byte[1048576];int count;
                        while((count=input.Read(buffer,0,buffer.Length))>0) {
                            cancellation.Token.ThrowIfCancellationRequested();
                            if(offset+count>sizes[index])throw new IOException("Download maior que o manifesto assinado.");
                            output.Write(buffer,0,count);offset+=count;Interlocked.Add(ref completed,count);
                        }
                    }
                    if(offset!=sizes[index])throw new IOException("Download incompleto.");
                }
                return;
            } catch {
                if(cancellation.IsCancellationRequested || attempt==2)throw;
                // A retry always resumes from the bytes actually persisted to disk.
                if(cancellation.Token.WaitHandle.WaitOne(1000*(attempt+1)))cancellation.Token.ThrowIfCancellationRequested();
            } finally {
                HttpWebRequest removed;requests.TryRemove(index,out removed);
                if(request!=null)request.Abort();
            }
        }
    }
    public void Wait() {
        try {job.GetAwaiter().GetResult();}
        catch(AggregateException error) {throw error.Flatten().InnerExceptions[0];}
    }
    public void Cancel() {
        cancellation.Cancel();
        foreach(var request in requests.Values) {try {request.Abort();}catch {}}
    }
    public void Dispose() {if(!IsCompleted)Cancel();}
}
