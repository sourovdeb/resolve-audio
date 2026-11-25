using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace VoiceMacro {
    public sealed class Dial:Control {
        public event EventHandler Changed,Committed;
        private double value;
        private int anchorY;
        private double anchorValue;
        private bool dragging;
        public string Caption="Depth",Description="Body / mud";
        public double Value {get{return value;}set{this.value=Math.Max(0,Math.Min(100,value));Invalidate();if(Changed!=null)Changed(this,EventArgs.Empty);}}
        public Dial() {
            SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer|ControlStyles.Selectable,true);
            TabStop=true;Size=new Size(190,220);Cursor=Cursors.Hand;
            AccessibleRole=AccessibleRole.Slider;
        }
        protected override void OnPaint(PaintEventArgs e) {
            base.OnPaint(e);var g=e.Graphics;g.SmoothingMode=SmoothingMode.AntiAlias;
            g.ScaleTransform(ClientSize.Width/190f,ClientSize.Height/220f);
            var ring=new Rectangle(35,42,120,120);
            using(var pen=new Pen(Color.FromArgb(204,211,207),9))g.DrawArc(pen,ring,135,270);
            using(var pen=new Pen(Color.FromArgb(22,125,102),9))g.DrawArc(pen,ring,135,(float)(270*value/100));
            double rad=(135+270*value/100)*Math.PI/180;
            using(var pen=new Pen(Color.FromArgb(30,40,37),4))g.DrawLine(pen,95+(float)Math.Cos(rad)*36,102+(float)Math.Sin(rad)*36,95+(float)Math.Cos(rad)*48,102+(float)Math.Sin(rad)*48);
            using(var title=new Font("Segoe UI",11,FontStyle.Bold))Draw(g,Caption,title,new Rectangle(0,4,190,28));
            using(var number=new Font("Segoe UI",22,FontStyle.Regular))Draw(g,Math.Round(value).ToString(),number,new Rectangle(50,80,90,44));
            using(var text=new Font("Segoe UI",9))Draw(g,Description,text,new Rectangle(0,178,190,24));
            if(Focused)ControlPaint.DrawFocusRectangle(g,new Rectangle(5,1,180,211));
        }
        private void Draw(Graphics g,string s,Font font,Rectangle bounds) {
            using(var brush=new SolidBrush(ForeColor))using(var format=new StringFormat{Alignment=StringAlignment.Center,LineAlignment=StringAlignment.Center})g.DrawString(s,font,brush,bounds,format);
        }
        protected override void OnMouseDown(MouseEventArgs e) {base.OnMouseDown(e);if(e.Button!=MouseButtons.Left)return;Focus();dragging=true;Capture=true;anchorY=e.Y;anchorValue=value;}
        protected override void OnMouseMove(MouseEventArgs e) {base.OnMouseMove(e);if(dragging)Value=anchorValue+(anchorY-e.Y)*220.0/ClientSize.Height*((ModifierKeys&Keys.Shift)!=0?0.1:0.7);}
        protected override void OnMouseUp(MouseEventArgs e) {base.OnMouseUp(e);if(!dragging)return;dragging=false;Capture=false;if(Committed!=null)Committed(this,EventArgs.Empty);}
        protected override bool IsInputKey(Keys key) {return key==Keys.Up||key==Keys.Down||key==Keys.Left||key==Keys.Right||base.IsInputKey(key);}
        protected override void OnKeyDown(KeyEventArgs e) {
            base.OnKeyDown(e);
            if(e.KeyCode==Keys.Up||e.KeyCode==Keys.Right)Value+=1;
            else if(e.KeyCode==Keys.Down||e.KeyCode==Keys.Left)Value-=1;
            else if(e.KeyCode==Keys.Home)Value=0;
            else if(e.KeyCode==Keys.End)Value=100;
            else return;
            e.Handled=true;
        }
        protected override void OnKeyUp(KeyEventArgs e) {base.OnKeyUp(e);if(new[]{Keys.Up,Keys.Down,Keys.Left,Keys.Right,Keys.Home,Keys.End}.Contains(e.KeyCode)&&Committed!=null)Committed(this,EventArgs.Empty);}
        protected override void OnGotFocus(EventArgs e){base.OnGotFocus(e);Invalidate();}
        protected override void OnLostFocus(EventArgs e){base.OnLostFocus(e);Invalidate();}
    }
    public static class Paths {
        public static readonly string Root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"VoiceMacro");
        public static string LayoutFile {get{return Path.Combine(Root,"layout.json");}}
        public static string SessionFile {get{return Path.Combine(Root,"session.json");}}
        public static string RestoreFile {get{return Path.Combine(Root,"before-apply.json");}}
        public static string ProfileFile {get{return Path.Combine(Root,"track-profile.json");}}
        public static void Log(string text) {
            Directory.CreateDirectory(Root);string p=Path.Combine(Root,"events.log");
            if(File.Exists(p)&&new FileInfo(p).Length>1048576) File.Move(p,Path.Combine(Root,"events-"+DateTime.UtcNow.Ticks+".log"));
            File.AppendAllText(p,DateTime.UtcNow.ToString("o")+" "+text+Environment.NewLine);
        }
    }
    public sealed class MainForm:Form {
        private Dial depth,presence,control;
        private Label summary,status;
        private CheckBox auto;
        private bool loading,busy;
        private HashSet<string> verified=new HashSet<string>();
        private Layout layout=new Layout();
        private Preset preset=new Preset();
        private TrackProfile trackProfile=new TrackProfile();
        private string startupNote="Setup connects Fairlight's fields.";
        public MainForm() {
            Text="VoiceMacro 0.4 / Fairlight";ClientSize=new Size(660,525);
            FormBorderStyle=FormBorderStyle.FixedSingle;MaximizeBox=false;StartPosition=FormStartPosition.CenterScreen;
            AutoScaleMode=AutoScaleMode.Dpi;BackColor=Color.FromArgb(242,240,233);ForeColor=Color.FromArgb(28,38,35);
            Font=new Font("Segoe UI",9);
            try{if(File.Exists(Paths.LayoutFile)){layout=JsonFile.Read<Layout>(Paths.LayoutFile);layout.Validate();}}catch(Exception e){startupNote="Layout needs remapping.";Paths.Log(e.Message);}
            try{if(File.Exists(Paths.SessionFile)){preset=JsonFile.Read<Preset>(Paths.SessionFile);preset.Validate();}}catch{preset=new Preset();}
            try{if(File.Exists(Paths.ProfileFile)){var profile=JsonFile.Read<TrackProfile>(Paths.ProfileFile);profile.Validate();trackProfile=profile;}}
            catch(Exception e){Paths.Log(e.Message);}
            var top=new Panel{Location=new Point(0,0),Size=new Size(660,68),BackColor=Color.FromArgb(29,45,40)};Controls.Add(top);
            top.Controls.Add(new Label{Text="VOICE MACRO",Location=new Point(24,13),Size=new Size(280,30),ForeColor=Color.White,Font=new Font("Segoe UI",17,FontStyle.Bold)});
            top.Controls.Add(new Label{Text="DEPTH / PRESENCE / CONTROL",Location=new Point(354,24),Size=new Size(290,24),ForeColor=Color.FromArgb(183,213,197)});
            summary=new Label{Location=new Point(24,78),Size=new Size(610,38)};Controls.Add(summary);
            depth=MakeDial("Depth","Body / mud",30,preset.depth);
            presence=MakeDial("Presence","Definition / air",235,preset.presence);
            control=MakeDial("Control","Compression / gain",440,preset.control);
            ButtonAt("Setup",24,347,85,delegate{Setup();});
            ButtonAt("Apply",119,347,85,delegate{Apply(null);});
            ButtonAt("Restore",214,347,85,delegate{Restore();});
            ButtonAt("Save",309,347,75,delegate{Save();});
            ButtonAt("Load",394,347,75,delegate{LoadPreset();});
            ButtonAt("Recipe",479,347,75,delegate{ShowRecipe();});
            ButtonAt("Help",564,347,72,delegate{OpenHelp();});
            var profileButton=ButtonAt("Track profiles  ▾",24,392,193,delegate{});
            var profileMenu=BuildProfileMenu();
            profileButton.Click+=delegate{if(!busy)profileMenu.Show(profileButton,new Point(0,profileButton.Height));};
            ButtonAt("Match WAV…",234,392,192,delegate{OpenMatcher(false);});
            ButtonAt("Resolve tools…",443,392,193,ShowResolveTools);
            auto=new CheckBox{Text="Apply on release",Location=new Point(24,440),AutoSize=true};Controls.Add(auto);
            auto.CheckedChanged+=delegate{if(auto.Checked&&!Model.Keys(null).All(verified.Contains)){auto.Checked=false;status.Text="Verify EQ and Dynamics first.";}};
            var tip=new Label{Text="Drag up/down. Arrows adjust.",Location=new Point(354,442),Size=new Size(280,22)};Controls.Add(tip);
            status=new Label{Text=startupNote,Location=new Point(24,476),Size=new Size(612,39),ForeColor=Color.FromArgb(41,85,68)};Controls.Add(status);
            RefreshSummary();
            FormClosing+=delegate{if(busy)return;try{JsonFile.Write(Paths.SessionFile,Current());}catch{}};
            Disposed+=delegate{profileMenu.Dispose();};
            Shown+=delegate {BeginInvoke(new Action(delegate {OpenMatcher(true);}));};
        }
        private Dial MakeDial(string name,string desc,int x,double val) {
            var d=new Dial{Caption=name,Description=desc,Location=new Point(x,119),Value=val,AccessibleName=name};Controls.Add(d);
            d.Changed+=delegate{if(loading)return;RefreshSummary();if(status!=null)status.Text="Knobs changed. Apply to hear.";};
            d.Committed+=delegate{if(auto!=null&&auto.Checked&&!loading)Apply(name=="Control"?"Dynamics":"EQ");};
            return d;
        }
        private Button ButtonAt(string label,int x,int y,int width,Action handler) {
            var b=new Button{Text=label,Location=new Point(x,y),Size=new Size(width,34),FlatStyle=FlatStyle.Flat};
            b.Click+=delegate{if(!busy)handler();};Controls.Add(b);return b;
        }
        private Preset Current(){return new Preset{name=preset.name,depth=Math.Round(depth.Value),presence=Math.Round(presence.Value),control=Math.Round(control.Value),match=preset.match};}
        private void RefreshSummary() {
            if(depth==null||presence==null||control==null)return;
            var values=Model.Map(Current());
            summary.Text="Body "+Model.Number(values["body"])+" dB  /  Presence "+Model.Number(values["presence"])+
                         " dB  /  Ratio "+Model.Number(values["ratio"])+":1\n"+
                         (preset.match==null?"Mode: Voice shaping":"Mode: WAV reference match");
        }
        private void Error(Exception e) {
            Paths.Log(e.ToString());status.Text="Stopped. Check the message.";
            MessageBox.Show(this,e.Message+"\n\n"+(e.InnerException==null?"":e.InnerException.Message),"Voice Macro",MessageBoxButtons.OK,MessageBoxIcon.Information);
        }
        private void RunBridge(Action<IFieldAccess> action,string done) {
            if(busy)return;busy=true;Hide();
            try {
                using(var clipboard=new ClipboardLease())action(new WindowsBridge(layout));
                status.Text=done;Paths.Log(done);
            } catch(Exception e){verified.Clear();auto.Checked=false;Show();Error(e);} finally{busy=false;Show();Activate();}
        }
        private void Backup(Dictionary<string,double> values) {
            var snapshot=new Snapshot{time=DateTime.UtcNow.ToString("o"),values=values,layoutId=layout.id};
            JsonFile.Write(Paths.RestoreFile,snapshot);
            string history=Path.Combine(Paths.Root,"history",DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff")+".json");
            JsonFile.Write(history,snapshot);
        }
        private void Apply(string group) {
            if(!IsVerified(group))return;
            var values=Model.Map(Current());
            if(group!=null)values=values.Where(p=>Model.Find(p.Key).Group==group).ToDictionary(p=>p.Key,p=>p.Value);
            RunBridge(delegate(IFieldAccess a){Engine.Apply(a,values,Backup);},"Values verified. Listen in Resolve.");
        }
        private void Restore() {
            if(!File.Exists(Paths.RestoreFile)){status.Text="No restore snapshot exists.";return;}
            try {
                Snapshot s=JsonFile.Read<Snapshot>(Paths.RestoreFile);
                if(s==null||s.values==null||s.layoutId!=layout.id)throw new InvalidDataException("Snapshot belongs to another mapping.");
                auto.Checked=false;
                RunBridge(delegate(IFieldAccess a){Engine.Apply(a,s.values,Backup);},"Restored fields. Knobs remain proposals.");
            }catch(Exception e){Error(e);}
        }
        private void Setup() {
            auto.Checked=false;
            // The capture timer must keep running while both windows are hidden.
            var form=new SetupForm(layout,verified,this);
            Enabled=false;
            form.FormClosed+=delegate{
                Enabled=true;layout=form.CurrentLayout;verified=form.Verified;
                status.Text=verified.Count>0?"Mappings verified. Choose a track action.":"Verify a group before applying.";
                try{JsonFile.Write(Paths.LayoutFile,layout);}catch(Exception e){verified.Clear();Error(e);}
                Activate();
            };
            form.Show(this);
        }
        private bool IsVerified(string group) {
            if(Model.Keys(group).All(verified.Contains))return true;
            status.Text="Verify the required group in Setup.";
            return false;
        }
        private ContextMenuStrip BuildProfileMenu() {
            var menu=new ContextMenuStrip();
            AddProfileGroup(menu,"Voice (EQ + Dynamics)",null);
            AddProfileGroup(menu,"EQ gains","EQ");
            AddProfileGroup(menu,"Dynamics","Dynamics");
            AddProfileGroup(menu,"Mixer fader","Level");
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Save track profile…",null,delegate{SaveTrackProfile();});
            menu.Items.Add("Load track profile…",null,delegate{LoadTrackProfile();});
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Apply knobs to EQ only",null,delegate{Apply("EQ");});
            menu.Items.Add("Apply knobs to Dynamics only",null,delegate{Apply("Dynamics");});
            menu.Items.Add("Load WAV match plan…",null,delegate{LoadPlan();});
            menu.Items.Add("Clear WAV match",null,delegate{preset.match=null;RefreshSummary();status.Text="Voice shaping restored. Apply to hear.";});
            return menu;
        }
        private void AddProfileGroup(ContextMenuStrip menu,string name,string group) {
            var item=new ToolStripMenuItem(name);
            item.DropDownItems.Add("Copy",null,delegate{CopyGroup(group);});
            item.DropDownItems.Add("Paste",null,delegate{PasteGroup(group);});
            menu.Items.Add(item);
        }
        private void CopyGroup(string group) {
            if(!IsVerified(group))return;
            RunBridge(delegate(IFieldAccess bridge){
                var values=Engine.ReadAll(bridge,Model.Keys(group));
                var profile=new TrackProfile{values=new Dictionary<string,double>(trackProfile.values)};
                foreach(var value in values)profile.values[value.Key]=value.Value;
                SetTrackProfile(profile);
            },"Settings copied. Verify the destination before pasting.");
        }
        private void PasteGroup(string group) {
            if(!IsVerified(group))return;
            try{
                var values=trackProfile.Select(group);
                RunBridge(delegate(IFieldAccess bridge){Engine.Apply(bridge,values,Backup);},"Profile pasted and verified.");
            }catch(Exception e){Error(e);}
        }
        private void SetTrackProfile(TrackProfile profile) {
            profile.Validate();
            JsonFile.Write(Paths.ProfileFile,profile);
            trackProfile=profile;
        }
        private void SaveTrackProfile() {
            using(var dialog=new SaveFileDialog{Filter="VoiceMacro track profile|*.json",FileName="Track-Profile.json"}) {
                if(dialog.ShowDialog(this)!=DialogResult.OK)return;
                try{
                    if(trackProfile.values.Count==0)throw new InvalidOperationException("Copy a track group before saving.");
                    JsonFile.Write(dialog.FileName,trackProfile);status.Text="Track profile saved.";
                }catch(Exception e){Error(e);}
            }
        }
        private void LoadTrackProfile() {
            using(var dialog=new OpenFileDialog{Filter="VoiceMacro track profile|*.json"}) {
                if(dialog.ShowDialog(this)!=DialogResult.OK)return;
                try{SetTrackProfile(JsonFile.Read<TrackProfile>(dialog.FileName));status.Text="Profile loaded. Choose a group to paste.";}
                catch(Exception e){Error(e);}
            }
        }
        private void SetMatch(MatchCurve curve) {
            curve.Validate();
            if(preset.match==null) {
                loading=true;depth.Value=75;presence.Value=75;control.Value=45;loading=false;
            }
            preset.match=curve;
            RefreshSummary();status.Text="Match loaded. Turn knobs, then Apply.";
        }
        private void LoadPlan() {
            using(var dialog=new OpenFileDialog{Filter="VoiceMacro track match|*.json"}) {
                if(dialog.ShowDialog(this)!=DialogResult.OK)return;
                try{SetMatch(JsonFile.Read<MatchCurve>(dialog.FileName));}catch(Exception e){Error(e);}
            }
        }
        private void OpenMatcher(bool quickStart) {
            var strength=quickStart ? new Preset{depth=75,presence=75,control=45} : Current();
            using(var dialog=new MatcherForm(strength,quickStart)) {
                if(dialog.ShowDialog(this)==DialogResult.OK)SetMatch(dialog.Curve);
            }
        }
        private void Save() {
            using(var dialog=new SaveFileDialog{Filter="Voice Macro preset|*.json",FileName="My-Voice.json",InitialDirectory=Path.Combine(Paths.Root,"presets")}) {
                Directory.CreateDirectory(dialog.InitialDirectory);
                if(dialog.ShowDialog(this)!=DialogResult.OK)return;
                try{var p=Current();p.name=Path.GetFileNameWithoutExtension(dialog.FileName);p.Validate();JsonFile.Write(dialog.FileName,p);preset=p;status.Text="Knobs saved. Fairlight saves separately.";}catch(Exception e){Error(e);}
            }
        }
        private void LoadPreset() {
            using(var dialog=new OpenFileDialog{Filter="Voice Macro preset|*.json",InitialDirectory=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"presets")}) {
                if(dialog.ShowDialog(this)!=DialogResult.OK)return;
                try {
                    var p=JsonFile.Read<Preset>(dialog.FileName);p.Validate();preset=p;loading=true;
                    depth.Value=p.depth;presence.Value=p.presence;control.Value=p.control;loading=false;RefreshSummary();status.Text="Preset loaded. Click Apply.";
                }catch(Exception e){loading=false;Error(e);}
            }
        }
        private void ShowRecipe() {
            using(var f=new Form{Text="Recipe / Fairlight setup",Size=new Size(610,730),StartPosition=FormStartPosition.CenterParent}) {
                var t=new TextBox{Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,Font=new Font("Consolas",10),Text=Model.Recipe(Current())};f.Controls.Add(t);
                var b=new Button{Text="Copy recipe",Dock=DockStyle.Bottom,Height=38};b.Click+=delegate{Clipboard.SetText(t.Text);};f.Controls.Add(b);f.ShowDialog(this);
            }
        }
        private void ShowResolveTools() {
            using(var f=new Form{Text="Resolve tools",ClientSize=new Size(600,488),StartPosition=FormStartPosition.CenterParent}) {
                f.Controls.Add(new TextBox{Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,
                    Font=new Font("Segoe UI",11),Text=ResolveNotes.Text});
                f.ShowDialog(this);
            }
        }
        private void OpenHelp() {try{Process.Start(new ProcessStartInfo(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"START-HERE.html")){UseShellExecute=true});}catch(Exception e){Error(e);}}
    }
    public sealed class SetupForm:Form {
        public Layout CurrentLayout;
        public HashSet<string> Verified;
        private MainForm parent;
        private ListBox list;
        private Label note;
        private System.Windows.Forms.Timer timer;
        private int countdown;
        private string pending;
        public SetupForm(Layout layout,HashSet<string> verified,MainForm owner) {
            CurrentLayout=layout;Verified=new HashSet<string>(verified);parent=owner;Text="Connect Fairlight fields";ClientSize=new Size(660,560);StartPosition=FormStartPosition.CenterParent;
            Font=new Font("Segoe UI",10);AutoScaleMode=AutoScaleMode.Dpi;FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;
            Controls.Add(new Label{Text="1. Complete the Recipe in Fairlight.\n2. Open the control window.\n3. Select and capture a field.\n4. Hover its number for four seconds.\n5. Verify the group.",Location=new Point(20,16),Size=new Size(615,115)});
            list=new ListBox{Location=new Point(20,139),Size=new Size(615,190),Font=new Font("Consolas",10)};Controls.Add(list);Fill();
            AddButton("Capture field",20,342,140,CaptureField);
            AddButton("Verify group",174,342,150,Verify);
            AddButton("Clear mappings",338,342,145,Clear);
            AddButton("Done",497,342,137,delegate{Close();});
            note=new Label{Text="Map the mixer fader only for level copying.\nCheck the names and values during verification.\nKeep the mapped windows open during use.",Location=new Point(20,397),Size=new Size(615,145)};Controls.Add(note);
            timer=new System.Windows.Forms.Timer{Interval=1000};timer.Tick+=Tick;
            FormClosed+=delegate{timer.Stop();timer.Dispose();parent.Show();};
        }
        private void AddButton(string label,int x,int y,int w,Action a){var b=new Button{Text=label,Location=new Point(x,y),Size=new Size(w,37)};b.Click+=delegate{try{a();}catch(Exception e){Fail(e);}};Controls.Add(b);}
        private void Fill(){int index=list.SelectedIndex;list.Items.Clear();foreach(var f in Model.Fields){var b=CurrentLayout.fields.FirstOrDefault(x=>x.key==f.Key);list.Items.Add((b==null?"[ ] ":Verified.Contains(f.Key)?"[✓] ":"[+] ")+f.Group+" / "+f.Label+(b==null?"":" / "+b.title));}list.SelectedIndex=Math.Max(0,Math.Min(Model.Fields.Length-1,index));}
        private void CaptureField(){pending=Model.Fields[list.SelectedIndex].Key;countdown=4;Hide();parent.Hide();timer.Start();}
        private void Tick(object sender,EventArgs e) {
            if(--countdown>0)return;timer.Stop();
            try {
                Native.AbortCheck();var b=WindowsBridge.Capture(pending);
                var proposed=new Layout{fields=CurrentLayout.fields.Where(x=>x.key!=pending).ToList()};
                proposed.fields.Add(b);proposed.Validate();CurrentLayout=proposed;
                Verified.ExceptWith(Model.Keys(Model.Find(pending).Group));
                Fill();if(list.SelectedIndex<Model.Fields.Length-1)list.SelectedIndex++;
                note.Text="Captured: "+Model.Find(pending).Label+"\nWindow: "+b.title+"\nSelect Capture for the next.";
            }catch(Exception ex){Fail(ex);}finally{parent.Show();Show();Activate();}
        }
        private void Verify() {
            var group=Model.Fields[list.SelectedIndex].Group;
            var keys=Model.Keys(group);
            Verified.ExceptWith(keys);
            Hide();parent.Hide();
            try {
                using(var c=new ClipboardLease()) {
                    var result=Engine.ReadAll(new WindowsBridge(CurrentLayout),keys);
                    note.Text=group+" readback. Check each value.\n"+String.Join(" / ",result.Select(x=>x.Key+" "+Model.Number(x.Value)).ToArray());
                }
                Verified.UnionWith(keys);Fill();
            }catch(Exception e){Fail(e);}finally{parent.Show();Show();Activate();}
        }
        private void Clear(){CurrentLayout=new Layout();Verified.Clear();Fill();note.Text="Mappings cleared.";}
        private void Fail(Exception e){Fill();Paths.Log(e.ToString());parent.Show();Show();MessageBox.Show(this,e.Message,"Voice Macro setup");}
    }
    public static class Program {
        [STAThread] public static void Main() {
            try{Native.SetProcessDpiAwarenessContext(new IntPtr(-4));}catch(EntryPointNotFoundException){}
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
            Application.ThreadException+=delegate(object sender,System.Threading.ThreadExceptionEventArgs e){Paths.Log(e.Exception.ToString());MessageBox.Show(e.Exception.Message,"Voice Macro stopped");};
            Application.Run(new MainForm());
        }
    }
}
