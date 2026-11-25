using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace VoiceMacro {
    public sealed class MatcherForm : Form {
        private readonly TextBox reference, input, report;
        private readonly ComboBox level;
        private readonly Preset strength;
        private readonly List<Control> actions=new List<Control>();
        private bool running;
        public MatchCurve Curve { get; private set; }

        public MatcherForm(Preset strength) {
            this.strength=strength;
            Text="Match WAV";
            ClientSize=new Size(665,390);
            AutoScaleMode=AutoScaleMode.Dpi;
            Font=new Font("Segoe UI",9);
            StartPosition=FormStartPosition.CenterParent;
            FormBorderStyle=FormBorderStyle.FixedDialog;
            MaximizeBox=false;
            MinimizeBox=false;

            reference=PathRow("Reference",18,"WAV or profile|*.wav;*.json");
            string personal=Path.Combine(Paths.Root,"Reference-Profile.json");
            string packaged=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"Reference-Profile.json");
            reference.Text=File.Exists(personal)?personal:File.Exists(packaged)?packaged:"";
            input=PathRow("Target WAV",56,"WAV audio|*.wav");
            AddLabel("Loudness",20,104,80);
            level=new ComboBox{Location=new Point(110,100),Width=250,DropDownStyle=ComboBoxStyle.DropDownList};
            level.Items.AddRange(new object[]{"Match reference","YouTube starting point (−16 LUFS)","Keep target level"});
            level.SelectedIndex=0;
            Controls.Add(level);actions.Add(level);
            MakeButton("Match voice",20,146,145,async delegate{await Render("voice");});
            MakeButton("Match EQ",179,146,145,async delegate{await Render("eq");});
            MakeButton("Match level",338,146,145,async delegate{await Render("level");});
            MakeButton("Use with knobs",497,146,145,async delegate{await MakePlan();});
            AddLabel(String.Format(CultureInfo.InvariantCulture,"Depth {0:0}%  /  Presence {1:0}%  /  Control {2:0}%",
                strength.depth,strength.presence,strength.control),20,196,580);
            report=new TextBox{Location=new Point(20,225),Size=new Size(622,142),Multiline=true,
                ReadOnly=true,ScrollBars=ScrollBars.Vertical,Text="Choose the WAV to improve.\r\n"+
                "Match buttons write a new WAV. Use with knobs loads a Fairlight proposal.\r\n"+
                "WAV matching needs Python and FFmpeg. See START-HERE."};
            Controls.Add(report);
            FormClosing+=delegate(object sender,FormClosingEventArgs e){if(running)e.Cancel=true;};
        }

        private void AddLabel(string text,int x,int y,int width) {
            Controls.Add(new Label{Text=text,Location=new Point(x,y),Size=new Size(width,23)});
        }

        private TextBox PathRow(string label,int y,string filter) {
            AddLabel(label,20,y+3,87);
            var field=new TextBox{Location=new Point(110,y),Width=420,ReadOnly=true};
            Controls.Add(field);
            MakeButton("Browse…",544,y-2,98,delegate{
                using(var dialog=new OpenFileDialog{Filter=filter,CheckFileExists=true}) {
                    if(dialog.ShowDialog(this)==DialogResult.OK)field.Text=dialog.FileName;
                }
            });
            return field;
        }

        private void MakeButton(string text,int x,int y,int width,Action handler) {
            var button=new Button{Text=text,Location=new Point(x,y),Size=new Size(width,30)};
            button.Click+=delegate{if(!running)handler();};
            actions.Add(button);Controls.Add(button);
        }

        private string LoudnessMode { get { return new[]{"reference","youtube","keep"}[level.SelectedIndex]; } }

        private bool Ready(bool needReference) {
            if(!File.Exists(input.Text)) {
                report.Text="Choose the WAV to improve.";
                return false;
            }
            if(needReference&&!File.Exists(reference.Text)) {
                report.Text="Choose the reference WAV or reference profile.";
                return false;
            }
            return true;
        }

        private List<string> Args(string action,string output) {
            var args=new List<string>{action,input.Text,"--output",output};
            if(File.Exists(reference.Text)) { args.Add("--reference");args.Add(reference.Text); }
            return args;
        }

        private async Task Render(string mode) {
            if(!Ready(mode!="level"||LoudnessMode=="reference"))return;
            using(var dialog=new SaveFileDialog{Filter="WAV audio|*.wav",OverwritePrompt=false,
                FileName=Path.GetFileNameWithoutExtension(input.Text)+"-matched.wav",InitialDirectory=Path.GetDirectoryName(input.Text)}) {
                if(dialog.ShowDialog(this)!=DialogResult.OK)return;
                var args=Args("match",dialog.FileName);
                args.AddRange(new[]{"--mode",mode,"--loudness",LoudnessMode,"--depth",Model.Number(strength.depth),
                    "--presence",Model.Number(strength.presence),"--control",Model.Number(strength.control)});
                try {
                    string result=await Run(args);
                    report.Text=result.Trim()+Environment.NewLine+"Saved: "+dialog.FileName;
                }catch(Exception e){report.Text=e.Message;}
            }
        }

        private async Task MakePlan() {
            if(!Ready(true))return;
            string directory=Path.Combine(Path.GetTempPath(),"VoiceMacro-"+Guid.NewGuid().ToString("N"));
            string output=Path.Combine(directory,"track-match.json");
            try {
                Directory.CreateDirectory(directory);
                await Run(Args("plan",output));
                Curve=JsonFile.Read<MatchCurve>(output);
                Curve.Validate();
                DialogResult=DialogResult.OK;
            }catch(Exception e){report.Text=e.Message;}
            finally {
                try{File.Delete(output);Directory.Delete(directory);}catch(IOException){}catch(UnauthorizedAccessException){}
            }
        }

        private async Task<string> Run(List<string> args) {
            running=true;
            foreach(var action in actions)action.Enabled=false;
            report.Text="Measuring and processing audio…";
            try { return await Task.Run(()=>RunPython(args)); }
            finally {
                running=false;
                foreach(var action in actions)action.Enabled=true;
            }
        }

        private static string RunPython(List<string> args) {
            string script=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"matcher","match_voice.py");
            if(!File.Exists(script))throw new IOException("Matcher files are missing. Extract the full ZIP.");
            string command=String.Join(" ",new[]{script}.Concat(args).Select(Quote).ToArray());
            try { return Start("py.exe","-3 "+command); }
            catch(Win32Exception ex) {
                if(ex.NativeErrorCode!=2 && ex.NativeErrorCode!=3)throw;
                try { return Start("python.exe",command); }
                catch(Win32Exception missing) {
                    if(missing.NativeErrorCode!=2 && missing.NativeErrorCode!=3)throw;
                    throw new InvalidOperationException("Install Python 3, then reopen Resolve.",missing);
                }
            }
        }

        private static string Start(string program,string arguments) {
            var info=new ProcessStartInfo(program,arguments){CreateNoWindow=true,UseShellExecute=false,
                WorkingDirectory=AppDomain.CurrentDomain.BaseDirectory,RedirectStandardError=true,RedirectStandardOutput=true,
                StandardErrorEncoding=Encoding.UTF8,StandardOutputEncoding=Encoding.UTF8};
            info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
            using(var process=Process.Start(info)) {
                var output=process.StandardOutput.ReadToEndAsync();
                var errors=process.StandardError.ReadToEndAsync();
                process.WaitForExit();
                if(process.ExitCode!=0)throw new InvalidOperationException(String.IsNullOrWhiteSpace(errors.Result)?
                    "The matcher failed. Check Python and FFmpeg.":errors.Result.Trim());
                return output.Result;
            }
        }

        // Windows command-line quoting for a directly spawned process.
        private static string Quote(string value) {
            var result=new StringBuilder("\"");
            int slashes=0;
            foreach(char c in value) {
                if(c=='\\') { slashes++;continue; }
                result.Append('\\',c=='"'?2*slashes+1:slashes).Append(c);
                slashes=0;
            }
            return result.Append('\\',2*slashes).Append('"').ToString();
        }
    }

    internal static class ResolveNotes {
        internal const string Text=
            "COPY TRACK EQ OR DYNAMICS\r\n"+
            "Right-click the EQ or Dynamics graph in the source mixer strip. Copy there, then paste from the destination strip. That copies the whole native module. Track profiles in VoiceMacro copy the mapped numbers.\r\n\r\n"+
            "MATCH CLIPS IN RESOLVE\r\n"+
            "Right-click the reference clip. Under Clip Operations, open EQ Matcher or Level Matcher and capture its profile. Right-click the target clip and apply the profile. Choose Clip EQ to keep EQ local to that clip. Labels can vary by 21.x build.\r\n\r\n"+
            "DIALOGUE PROFILE\r\n"+
            "Resolve's Dialogue Matcher is under AI Tools. For a non-AI workflow, use Match WAV or copy the mapped track voice settings.\r\n\r\n"+
            "SAVE A PRESET OR MIX\r\n"+
            "Fairlight > Presets Library saves track, EQ, or Dynamics settings. Fairlight > Automation > Mix List > Save Mix stores a mixer snapshot. The VoiceMacro launcher lives under Workspace > Workflow Integrations.";
    }
}
