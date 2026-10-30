using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Forms = System.Windows.Forms;

[assembly:AssemblyTitle("SubForgeAI Studio Installer")]
[assembly:AssemblyProduct("SubForgeAI Studio")]
[assembly:AssemblyDescription("Instalador gráfico do SubForgeAI Studio")]
[assembly:AssemblyVersion("__VERSION__.0")]
[assembly:AssemblyFileVersion("__VERSION__.0")]

// Only the small graphical bootstrapper is compiled. The existing signed
// package and native parallel download engine are reused without repacking.
public sealed class InstallerGui {
    private const string Version = "__VERSION__";
    private const long DownloadBytes = __DOWNLOAD_BYTES__;
    private const long InstalledBytes = __INSTALLED_BYTES__;
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();
    private readonly StringBuilder log = new StringBuilder();
    private Window window;
    private DispatcherTimer timer;
    private Process worker;
    private string phase="ready", destination="", statusPath="", controlPath="", logPath="", error="";
    private long completed,total;
    private double speed;
    private int language;
    private bool closing, pendingControl, finishing, cancelRequested;
    private string screenshot;
    private string previewPhase;
    private string fixtureSource;
    private string fixtureDestination;
    private string testResult;
    private DateTime testStarted;

    private static readonly Dictionary<string,string[]> Words = new Dictionary<string,string[]> {
        {"title",new[]{"SubForgeAI Studio — Instalação","SubForgeAI Studio — Setup","SubForgeAI Studio — Instalación"}},
        {"version",new[]{"VERSÃO ","VERSION ","VERSIÓN "}},
        {"location",new[]{"Local de instalação","Install location","Ubicación"}},
        {"download",new[]{"Baixar arquivos","Download files","Descargar archivos"}},
        {"verify",new[]{"Verificar","Verify","Verificar"}},
        {"finish",new[]{"Concluir","Finish","Finalizar"}},
        {"heading",new[]{"Instale o SubForgeAI","Install SubForgeAI","Instala SubForgeAI"}},
        {"working",new[]{"Instalando o SubForgeAI","Installing SubForgeAI","Instalando SubForgeAI"}},
        {"subtitle",new[]{"Seu estúdio de legendas começa aqui.","Your subtitle studio starts here.","Tu estudio de subtítulos empieza aquí."}},
        {"workingSub",new[]{"Estamos preparando seu estúdio de legendas.","We are preparing your subtitle studio.","Estamos preparando tu estudio de subtítulos."}},
        {"ready",new[]{"Pronto para instalar","Ready to install","Listo para instalar"}},
        {"readyHint",new[]{"Download verificado e retomada automática","Verified download and automatic resume","Descarga verificada y reanudación automática"}},
        {"preparing",new[]{"Preparando instalação","Preparing installation","Preparando instalación"}},
        {"downloading",new[]{"Baixando arquivos","Downloading files","Descargando archivos"}},
        {"paused",new[]{"Download pausado","Download paused","Descarga pausada"}},
        {"verifying",new[]{"Verificando integridade","Verifying integrity","Verificando integridad"}},
        {"combining",new[]{"Preparando arquivos","Preparing files","Preparando archivos"}},
        {"extracting",new[]{"Extraindo aplicativo","Extracting application","Extrayendo aplicación"}},
        {"complete",new[]{"Instalação concluída","Installation complete","Instalación completada"}},
        {"failed",new[]{"Não foi possível concluir","Installation could not finish","No se pudo completar"}},
        {"cancelled",new[]{"Instalação cancelada","Installation cancelled","Instalación cancelada"}},
        {"resumeHint",new[]{"Retomada automática ativada","Automatic resume enabled","Reanudación automática activada"}},
        {"preserved",new[]{"Os arquivos baixados foram preservados para continuar depois.","Downloaded files were kept so you can resume later.","Los archivos descargados se conservaron para continuar después."}},
        {"setupHint",new[]{"Sem instalar Python ou outros programas à parte.","No separate Python or other software installation required.","No necesitas instalar Python ni otros programas por separado."}},
        {"models",new[]{"Os modelos de IA serão escolhidos no Studio.","AI models will be selected inside Studio.","Los modelos de IA se elegirán en Studio."}},
        {"folder",new[]{"Pasta de instalação","Installation folder","Carpeta de instalación"}},
        {"browse",new[]{"Escolher","Browse","Elegir"}},
        {"pick",new[]{"Escolha a pasta que receberá o SubForgeAI","Choose the folder that will contain SubForgeAI","Elige la carpeta que contendrá SubForgeAI"}},
        {"connections",new[]{"Conexões","Connections","Conexiones"}},
        {"auto",new[]{"4 · Automático","4 · Automatic","4 · Automático"}},
        {"compat",new[]{"1 · Compatibilidade","1 · Compatibility","1 · Compatibilidad"}},
        {"details",new[]{"Ver detalhes","View details","Ver detalles"}},
        {"cancel",new[]{"Cancelar","Cancel","Cancelar"}},
        {"cancelling",new[]{"Cancelando…","Cancelling…","Cancelando…"}},
        {"close",new[]{"Fechar","Close","Cerrar"}},
        {"install",new[]{"Instalar","Install","Instalar"}},
        {"pause",new[]{"Pausar download","Pause download","Pausar descarga"}},
        {"resume",new[]{"Continuar download","Resume download","Continuar descarga"}},
        {"retry",new[]{"Tentar novamente","Try again","Reintentar"}},
        {"open",new[]{"Abrir Studio","Open Studio","Abrir Studio"}},
        {"downloadSize",new[]{"Download: ","Download: ","Descarga: "}},
        {"appSize",new[]{"Aplicativo: ","Application: ","Aplicación: "}},
        {"of",new[]{" de "," of "," de "}},
        {"doneHint",new[]{"Tudo pronto. Abra o Studio para escolher os modelos.","All set. Open Studio to choose your models.","Todo listo. Abre Studio para elegir los modelos."}},
        {"existing",new[]{"A pasta já existe. Escolha outra pasta para preservar seus arquivos.","That folder already exists. Choose another location to preserve your files.","La carpeta ya existe. Elige otra para conservar tus archivos."}},
        {"absolute",new[]{"Escolha um caminho absoluto e uma pasta de destino nova.","Choose an absolute path and a new destination folder.","Elige una ruta absoluta y una carpeta de destino nueva."}},
        {"missing",new[]{"Extraia todos os arquivos do ZIP antes de abrir o instalador.","Extract all ZIP files before opening the installer.","Extrae todos los archivos del ZIP antes de abrir el instalador."}},
        {"unknown",new[]{"Veja os detalhes para identificar o problema. Downloads parciais foram preservados.","View details to identify the problem. Partial downloads were preserved.","Consulta los detalles para identificar el problema. Se conservaron las descargas parciales."}}
    };

    [STAThread]
    public static int Main(string[] args) {
        try { return new InstallerGui().Run(args); }
        catch(Exception e) { MessageBox.Show(e.Message,"SubForgeAI Studio",MessageBoxButton.OK,MessageBoxImage.Error); return 1; }
    }
    private T Find<T>(string name) where T:class { return window.FindName(name) as T; }
    private string T(string key) { return Words[key][language]; }
    private void Text(string name,string value) { Find<TextBlock>(name).Text=value; }
    private void Button(string name,string value) { Find<Button>(name).Content=value; }
    private bool Busy { get {return worker!=null && !worker.HasExited;} }
    private CultureInfo Culture { get {return CultureInfo.GetCultureInfo(new[]{"pt-BR","en-US","es-ES"}[language]);} }
    private string Size(double value) {return (value/1000000000d).ToString("N1",Culture)+" GB";}
    private static string Quote(string value) {
        // Windows CommandLineToArgvW quoting, including a trailing backslash.
        var b=new StringBuilder("\"");int slashes=0;
        foreach(char c in value) { if(c=='\\'){slashes++;continue;} if(c=='\"'){b.Append('\\',slashes*2+1);b.Append(c);slashes=0;continue;}b.Append('\\',slashes);slashes=0;b.Append(c); }
        b.Append('\\',slashes*2);b.Append('"');return b.ToString();
    }
    private int Run(string[] args) {
        for(int i=0;i<args.Length;i++) {
            if(args[i]=="--preview" && i+1<args.Length)previewPhase=args[++i];
            else if(args[i]=="--screenshot" && i+1<args.Length)screenshot=Path.GetFullPath(args[++i]);
            else if(args[i]=="--fixture-source" && i+1<args.Length)fixtureSource=Path.GetFullPath(args[++i]);
            else if(args[i]=="--fixture-destination" && i+1<args.Length)fixtureDestination=Path.GetFullPath(args[++i]);
            else if(args[i]=="--test-result" && i+1<args.Length)testResult=Path.GetFullPath(args[++i]);
            else if(args[i]=="--language" && i+1<args.Length){string code=args[++i];language=code=="en"?1:code=="es"?2:0;}
        }
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("InstallerWindow.xaml"))window=(Window)XamlReader.Load(stream);
        var app=new Application();
        window.MaxHeight=SystemParameters.WorkArea.Height;window.MaxWidth=SystemParameters.WorkArea.Width;
        try {using(var icon=System.Drawing.Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location))window.Icon=Imaging.CreateBitmapSourceFromHIcon(icon.Handle,Int32Rect.Empty,BitmapSizeOptions.FromEmptyOptions());}catch{}
        Find<TextBox>("Destination").Text=fixtureDestination ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"SubForgeAI");
        Find<ComboBox>("Language").SelectedIndex=language;
        Find<Button>("Minimize").Click+=(s,e)=>window.WindowState=WindowState.Minimized;
        Find<Button>("Close").Click+=(s,e)=>window.Close();
        Find<Border>("TitleBar").MouseLeftButtonDown+=(s,e)=>{if(e.ClickCount==1)window.DragMove();};
        Find<Button>("Browse").Click+=(s,e)=>Browse();
        Find<Button>("Primary").Click+=(s,e)=>Primary();
        Find<Button>("Secondary").Click+=(s,e)=>{if(Busy)Cancel(false);else window.Close();};
        Find<Button>("Details").Click+=(s,e)=>ShowDetails();
        Find<ComboBox>("Language").SelectionChanged+=(s,e)=>{language=Find<ComboBox>("Language").SelectedIndex;Render();};
        window.Closing+=Closing;
        timer=new DispatcherTimer{Interval=TimeSpan.FromMilliseconds(250)};timer.Tick+=(s,e)=>Tick();timer.Start();
        if(previewPhase!=null) {phase=previewPhase;destination=@"F:\SubForgeAI";Find<TextBox>("Destination").Text=destination;total=phase=="ready"?0:DownloadBytes;completed=(long)(total*.64);speed=phase=="download"?18400000:0;}
        Render();
        window.ContentRendered+=(s,e)=>{
            if(screenshot!=null && previewPhase!=null)Capture();
            if(fixtureSource!=null && fixtureDestination!=null && testResult!=null){testStarted=DateTime.UtcNow;Start();}
        };
        app.Run(window);timer.Stop();return phase=="error"?1:0;
    }
    private void Browse() {
        using(var picker=new Forms.FolderBrowserDialog()) {
            picker.Description=T("pick");picker.SelectedPath=Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            if(picker.ShowDialog(new Owner(new WindowInteropHelper(window).Handle))==Forms.DialogResult.OK)Find<TextBox>("Destination").Text=Path.Combine(picker.SelectedPath,"SubForgeAI");
        }
    }
    private sealed class Owner:Forms.IWin32Window {public IntPtr Handle{get;private set;}public Owner(IntPtr handle){Handle=handle;}}
    private void Primary() {
        if(phase=="complete") {try{Process.Start(new ProcessStartInfo(Path.Combine(destination,"SubForgeAI Studio.exe")){UseShellExecute=true,WorkingDirectory=destination});window.Close();}catch(Exception e){error=e.Message;ShowDetails();}return;}
        if(Busy) {if(phase=="download")SendControl("pause");else if(phase=="paused")SendControl("resume");return;}
        Start();
    }
    private void Start() {
        try {
            destination=Find<TextBox>("Destination").Text.Trim();
            if(!Path.IsPathRooted(destination))throw new InvalidOperationException(T("absolute"));
            destination=Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar);
            if(Directory.Exists(destination)||File.Exists(destination))throw new InvalidOperationException(T("existing"));
            string local=Environment.GetEnvironmentVariable("LOCALAPPDATA");if(String.IsNullOrWhiteSpace(local))local=Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var session=Path.Combine(local,"SubForgeAI-install","ui",Guid.NewGuid().ToString("N"));Directory.CreateDirectory(session);
            var home=session;
            foreach(string name in new[]{"Instalar.ps1","DownloadEngine.cs"}) {
                using(var input=Assembly.GetExecutingAssembly().GetManifestResourceStream(name)) {
                    if(input==null)throw new InvalidOperationException(T("missing"));
                    using(var output=File.Create(Path.Combine(home,name)))input.CopyTo(output);
                }
            }
            statusPath=Path.Combine(session,"progress.json");controlPath=Path.Combine(session,"control.json");logPath=Path.Combine(session,"install.log");
            error="";lock(log){log.Clear();}phase="prepare";pendingControl=false;completed=0;total=0;speed=0;finishing=false;cancelRequested=false;closing=false;
            var arguments="-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "+Quote(Path.Combine(home,"Instalar.ps1"))+" -NoLaunch -DestinationPath "+Quote(destination)+" -ProgressPath "+Quote(statusPath)+" -ControlPath "+Quote(controlPath)+" -ParentProcessId "+Process.GetCurrentProcess().Id+" -Connections "+(Find<ComboBox>("Connections").SelectedIndex==1?"1":"4");
            if(fixtureSource!=null)arguments+=" -SourceDirectory "+Quote(fixtureSource);
            var start=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),@"WindowsPowerShell\v1.0\powershell.exe"),arguments){UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,WorkingDirectory=home,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
            worker=new Process{StartInfo=start};worker.OutputDataReceived+=(s,e)=>AppendLog(e.Data);worker.ErrorDataReceived+=(s,e)=>AppendLog(e.Data);
            worker.Start();worker.BeginOutputReadLine();worker.BeginErrorReadLine();Render();
        }catch(Exception e){if(worker!=null){worker.Dispose();worker=null;}error=e.Message;phase="error";Render();if(testResult!=null){File.WriteAllText(testResult,json.Serialize(new{phase=phase,exit_code=1,destination=destination,error=error}));window.Close();}}
    }
    private void AppendLog(string line){if(line==null)return;lock(log){log.AppendLine(line);if(log.Length>64000)log.Remove(0,log.Length-64000);}}
    private bool SendControl(string action) {
        if(controlPath.Length==0)return false;
        try {
            var temporary=controlPath+".new";File.WriteAllText(temporary,json.Serialize(new Dictionary<string,string>{{"action",action}}),new UTF8Encoding(false));
            for(int i=0;;i++) {try {if(File.Exists(controlPath))File.Replace(temporary,controlPath,null);else File.Move(temporary,controlPath);break;}catch(UnauthorizedAccessException){File.WriteAllText(controlPath,json.Serialize(new Dictionary<string,string>{{"action",action}}),new UTF8Encoding(false));break;}catch(IOException){if(i==5)throw;Thread.Sleep(10);}}
            pendingControl=true;Render();return true;
        }catch(Exception e){pendingControl=false;error=e.Message;ShowDetails();return false;}
    }
    private void Cancel(bool close){closing=close;cancelRequested=true;if(!SendControl("cancel")){closing=false;cancelRequested=false;}Render();}
    private void Closing(object sender,CancelEventArgs e){if(Busy){e.Cancel=true;Cancel(true);}}
    private void Tick() {
        if(worker==null)return;
        try {
            if(File.Exists(statusPath)) {
                string content;using(var stream=new FileStream(statusPath,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))using(var reader=new StreamReader(stream))content=reader.ReadToEnd();
                if(content.Length<65536) {
                    var state=json.Deserialize<Dictionary<string,object>>(content);
                    if(state==null||!state.ContainsKey("stage")||!state.ContainsKey("completed")||!state.ContainsKey("total")||!state.ContainsKey("speed"))return;
                    string next=Convert.ToString(state["stage"]);
                    if(next!=phase){pendingControl=false;phase=next;}
                    completed=Convert.ToInt64(state["completed"]);total=Convert.ToInt64(state["total"]);speed=Convert.ToDouble(state["speed"]);
                    if((phase=="error"||phase=="cancelled")&&state.ContainsKey("message"))error=Convert.ToString(state["message"]);
                }
            }
            if(worker.HasExited&&!finishing) {
                finishing=true;worker.WaitForExit();int code=worker.ExitCode;worker.Dispose();worker=null;pendingControl=false;cancelRequested=false;
                if(code==0&&File.Exists(Path.Combine(destination,"SubForgeAI Studio.exe")))phase="complete";
                else if(code==2)phase="cancelled";
                else {phase="error";if(error.Length==0)error=T("unknown");}
                lock(log){File.WriteAllText(logPath,log.ToString(),new UTF8Encoding(true));}
                if(testResult!=null) {File.WriteAllText(testResult,json.Serialize(new{phase=phase,exit_code=code,destination=destination,log=logPath}));Render();if(screenshot!=null)Capture();window.Close();return;}
                if(closing){window.Close();return;}
            }
            if(testResult!=null&&DateTime.UtcNow-testStarted>TimeSpan.FromSeconds(90)&&Busy)Cancel(true);
            Render();
        }catch(IOException){}catch(ArgumentException){}catch(InvalidOperationException){}
    }
    private void Render() {
        window.Title=T("title");Text("WindowLabel",T("title"));Text("Version",T("version")+Version);
        for(int i=0;i<4;i++)Text("Label"+i,T(new[]{"location","download","verify","finish"}[i]));
        bool busy=Busy||(previewPhase!=null&&phase!="ready"&&phase!="complete"&&phase!="error"&&phase!="cancelled");bool done=phase=="complete";bool ready=phase=="ready";
        Text("Heading",done?T("complete"):(busy?T("working"):T("heading")));Text("Subtitle",busy?T("workingSub"):T("subtitle"));
        string key="ready";int step=0;
        switch(phase){case "prepare":key="preparing";break;case "download":key="downloading";step=1;break;case "paused":key="paused";step=1;break;case "verify":key="verifying";step=2;break;case "combine":key="combining";step=2;break;case "extract":key="extracting";step=2;break;case "complete":key="complete";step=3;break;case "cancelled":key="cancelled";break;case "error":key="failed";break;}
        Text("StageTitle",T(key));Text("StageHint",phase=="paused"?T("preserved"):T(ready?"readyHint":"resumeHint"));Text("FolderLabel",T("folder"));Text("ModelsHint",T("models"));
        Text("StageIcon",done?"✓":phase=="paused"?"Ⅱ":phase=="error"?"!":"↓");
        Text("Detail",phase=="error"?error:phase=="cancelled"?T("preserved"):done?T("doneHint"):T("setupHint"));
        Button("Browse",T("browse"));Text("ConnectionLabel",T("connections"));Button("Details",T("details"));
        var connections=Find<ComboBox>("Connections");((ComboBoxItem)connections.Items[0]).Content=T("auto");((ComboBoxItem)connections.Items[1]).Content=T("compat");
        Find<ProgressBar>("Progress").IsIndeterminate=busy&&total==0&&phase!="paused";
        double percent=total>0?Math.Min(100,100d*completed/total):0;
        if(done)percent=100;Find<ProgressBar>("Progress").Value=percent;Text("Percent",((int)Math.Round(percent)).ToString()+"%");
        Text("Amount",done?T("appSize")+Size(InstalledBytes):total>0?Size(completed)+T("of")+Size(total):T("downloadSize")+Size(DownloadBytes));
        Text("Speed",done?"":phase=="download"?(speed/1000000d).ToString("N1",Culture)+" MB/s":T("appSize")+Size(InstalledBytes));
        Find<TextBox>("Destination").IsReadOnly=busy||done;Find<Button>("Browse").IsEnabled=!busy&&!done;connections.IsEnabled=!busy&&!done;
        Find<StackPanel>("ConnectionRow").Visibility=busy||done?Visibility.Collapsed:Visibility.Visible;
        Button("Secondary",T(cancelRequested?"cancelling":busy?"cancel":"close"));Find<Button>("Secondary").IsEnabled=!cancelRequested;
        string primary=done?"open":phase=="download"?"pause":phase=="paused"?"resume":(phase=="error"||phase=="cancelled")?"retry":"install";
        Button("Primary",T(primary));Find<Button>("Primary").IsEnabled=!pendingControl&&(!busy||phase=="download"||phase=="paused");
        for(int i=0;i<4;i++) {
            Find<Border>("Step"+i).Background=new SolidColorBrush((Color)ColorConverter.ConvertFromString(i==step?"#322747":"#00000000"));
            Text("Glyph"+i,(i<step||done)?"✓":(i+1).ToString());Find<TextBlock>("Glyph"+i).Foreground=new SolidColorBrush((Color)ColorConverter.ConvertFromString(i<=step?"#A78BFA":"#69717F"));
        }
    }
    private void ShowDetails() {
        string text;lock(log)text=log.ToString();if(error.Length>0)text=error+Environment.NewLine+Environment.NewLine+text;
        if(logPath.Length>0)text+=Environment.NewLine+logPath;
        var details=new Window{Title=T("details"),Owner=window,Width=760,Height=430,Background=new SolidColorBrush(Color.FromRgb(16,18,22)),WindowStartupLocation=WindowStartupLocation.CenterOwner,Content=new TextBox{Text=text,IsReadOnly=true,TextWrapping=TextWrapping.Wrap,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,Margin=new Thickness(16)}};details.ShowDialog();
    }
    private void Capture() {
        window.UpdateLayout();var bitmap=new RenderTargetBitmap((int)window.ActualWidth,(int)window.ActualHeight,96,96,PixelFormats.Pbgra32);bitmap.Render(window);var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(bitmap));Directory.CreateDirectory(Path.GetDirectoryName(screenshot));using(var stream=File.Create(screenshot))encoder.Save(stream);
        if(previewPhase!=null)window.Close();
    }
}
