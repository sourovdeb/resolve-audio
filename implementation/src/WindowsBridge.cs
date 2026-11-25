using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace VoiceMacro {
    public static class Native {
        [StructLayout(LayoutKind.Sequential)] public struct POINT {public int X,Y; public POINT(int x,int y){X=x;Y=y;}}
        [StructLayout(LayoutKind.Sequential)] public struct RECT {public int Left,Top,Right,Bottom;}
        [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT {public int dx,dy;public uint mouseData,dwFlags,time; public UIntPtr extra;}
        [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT {public ushort vk,scan;public uint flags,time;public UIntPtr extra;}
        [StructLayout(LayoutKind.Explicit)] public struct UNION {
            [FieldOffset(0)] public MOUSEINPUT mouse;
            [FieldOffset(0)] public KEYBDINPUT key;
        }
        [StructLayout(LayoutKind.Sequential)] public struct INPUT {public uint type;public UNION data;}
        public delegate bool EnumProc(IntPtr window,IntPtr state);
        [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback,IntPtr state);
        [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT point);
        [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
        [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT point);
        [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr window,uint flags);
        [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
        [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
        [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr window);
        [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr window,out RECT rect);
        [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr window,ref POINT point);
        [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr window,ref POINT point);
        [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window,out uint process);
        [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr window,StringBuilder text,int length);
        [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr window);
        [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr context);
        [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
        [DllImport("user32.dll",SetLastError=true)] public static extern uint SendInput(uint count,INPUT[] inputs,int size);
        public static string Title(IntPtr window) {var s=new StringBuilder(1024);GetWindowText(window,s,s.Capacity);return s.ToString();}
        public static IntPtr Root(IntPtr window) {return GetAncestor(window,2);}
        public static bool IsResolve(IntPtr window) {
            uint pid;GetWindowThreadProcessId(window,out pid);
            try {using(var p=Process.GetProcessById((int)pid)) return String.Equals(p.ProcessName,"Resolve",StringComparison.OrdinalIgnoreCase);}
            catch{return false;}
        }
        public static void AbortCheck() {
            if((GetAsyncKeyState(0x1B)&0x8000)!=0) throw new OperationCanceledException("Stopped with Escape.");
        }
        public static void ModifiersCheck() {
            foreach(int vk in new[]{0x10,0x11,0x12,0x5B,0x5C})
                if((GetAsyncKeyState(vk)&0x8000)!=0) throw new InvalidOperationException("Release Shift, Ctrl, Alt, Windows.");
        }
        public static void Send(INPUT[] data) {
            AbortCheck();
            if(SendInput((uint)data.Length,data,Marshal.SizeOf(typeof(INPUT)))!=(uint)data.Length)
                throw new InvalidOperationException("Windows refused input. Check privileges.");
        }
        public static INPUT Key(ushort key,bool up) {return new INPUT{type=1,data=new UNION{key=new KEYBDINPUT{vk=key,flags=up?2u:0u}}};}
        public static void Press(ushort key) {Send(new[]{Key(key,false),Key(key,true)});}
        public static void Ctrl(ushort key) {Send(new[]{Key(0x11,false),Key(key,false),Key(key,true),Key(0x11,true)});}
        public static void Click() {Send(new[]{new INPUT{type=0,data=new UNION{mouse=new MOUSEINPUT{dwFlags=2}}},new INPUT{type=0,data=new UNION{mouse=new MOUSEINPUT{dwFlags=4}}}});}
        public static void Type(string s) {
            var inputs=new List<INPUT>();
            foreach(char c in s) {
                inputs.Add(new INPUT{type=1,data=new UNION{key=new KEYBDINPUT{scan=c,flags=4}}});
                inputs.Add(new INPUT{type=1,data=new UNION{key=new KEYBDINPUT{scan=c,flags=6}}});
            }
            Send(inputs.ToArray());
        }
    }
    public sealed class ClipboardLease:IDisposable {
        private DataObject saved;
        public ClipboardLease() {
            var source=Clipboard.GetDataObject();
            if(source==null) return;
            saved=new DataObject();
            foreach(string fmt in source.GetFormats(false)) {
                object item=source.GetData(fmt,false);
                var stream=item as MemoryStream;
                if(stream!=null) item=new MemoryStream(stream.ToArray());
                if(item!=null) saved.SetData(fmt,false,item);
            }
        }
        public void Dispose() {
            if(saved==null) Clipboard.Clear(); else Clipboard.SetDataObject(saved,true,5,60);
        }
    }
    public sealed class WindowsBridge:IFieldAccess {
        public readonly Layout Layout;
        private Dictionary<string,IntPtr> windows=new Dictionary<string,IntPtr>();
        private Dictionary<string,bool> comma=new Dictionary<string,bool>();
        public WindowsBridge(Layout layout){Layout=layout;layout.Validate();}
        public static Binding Capture(string key) {
            Model.Find(key); Native.POINT p;Native.GetCursorPos(out p);
            IntPtr root=Native.Root(Native.WindowFromPoint(p));
            if(root==IntPtr.Zero || !Native.IsResolve(root)) throw new InvalidOperationException("Hover a Resolve numeric field.");
            Native.RECT rect;Native.GetClientRect(root,out rect);Native.ScreenToClient(root,ref p);
            string title=Native.Title(root);
            if(String.IsNullOrWhiteSpace(title)) throw new InvalidOperationException("Window needs a title.");
            return new Binding{key=key,title=title,width=rect.Right,height=rect.Bottom,x=p.X,y=p.Y,dpi=(int)Native.GetDpiForWindow(root)};
        }
        public void Validate(string[] keys) {
            Native.AbortCheck();Native.ModifiersCheck();Layout.Validate();
            foreach(string key in keys) {
                Binding b=Layout.fields.SingleOrDefault(x=>x.key==key);
                if(b==null) throw new InvalidOperationException("Map this field: "+Model.Find(key).Label);
                var candidates=new List<IntPtr>();
                Native.EnumWindows(delegate(IntPtr w,IntPtr _) {
                    if(Native.IsWindowVisible(w)&&!Native.IsIconic(w)&&Native.Title(w)==b.title&&Native.IsResolve(w)) candidates.Add(w);
                    return true;
                },IntPtr.Zero);
                if(candidates.Count!=1) throw new InvalidOperationException("Open the mapped window:\n"+b.title);
                IntPtr window=candidates[0]; Native.RECT r;Native.GetClientRect(window,out r);
                if(r.Right!=b.width || r.Bottom!=b.height || Native.GetDpiForWindow(window)!=b.dpi)
                    throw new InvalidOperationException("Window layout changed. Remap fields.");
                windows[key]=window;
            }
            // Different groups must have different floating windows.
            var selected=keys.Select(k=>new {group=Model.Find(k).Group,w=windows[k]}).ToArray();
            if(selected.Any(a=>a.group=="EQ" && selected.Any(b=>b.group=="Dynamics" && a.w==b.w)))
                throw new InvalidOperationException("Use EQ and Dynamics windows.");
        }
        private Binding Bind(string key) {return Layout.fields.Single(x=>x.key==key);}
        private void Guard(string key) {
            Native.AbortCheck();
            IntPtr w=windows[key];Binding b=Bind(key);
            if(Native.Root(Native.GetForegroundWindow())!=w || !Native.IsResolve(w) || Native.Title(w)!=b.title)
                throw new InvalidOperationException("Focus changed. Operation stopped.");
            Native.RECT r;Native.GetClientRect(w,out r);
            if(r.Right!=b.width || r.Bottom!=b.height || Native.GetDpiForWindow(w)!=b.dpi)
                throw new InvalidOperationException("Window changed. Operation stopped.");
        }
        private void SelectField(string key) {
            Validate(new[]{key});IntPtr w=windows[key];Binding b=Bind(key);
            var p=new Native.POINT(b.x,b.y);Native.ClientToScreen(w,ref p);
            Native.SetForegroundWindow(w);Thread.Sleep(100);
            if(Native.Root(Native.GetForegroundWindow())!=w && Native.Root(Native.WindowFromPoint(p))==w) {
                Native.SetCursorPos(p.X,p.Y);Native.Click();Thread.Sleep(100);
            }
            Guard(key);
            if(Native.Root(Native.WindowFromPoint(p))!=w) throw new InvalidOperationException("Field covered. Move overlapping windows.");
            Native.SetCursorPos(p.X,p.Y);Guard(key);Native.Click();Thread.Sleep(60);Guard(key);Native.Click();
            Thread.Sleep(80);Guard(key);Native.Ctrl(0x41);Thread.Sleep(50);Guard(key);
        }
        private double CopyValue(string key) {
            string sentinel="VM_"+Guid.NewGuid().ToString("N");Clipboard.SetText(sentinel);
            Guard(key);Native.Ctrl(0x43);
            for(int i=0;i<15;i++) {
                Thread.Sleep(40);Guard(key);
                if(Clipboard.ContainsText()) {
                    string text=Clipboard.GetText();
                    if(text!=sentinel) {
                        double v=Model.Parse(text,Model.Find(key));
                        comma[key]=text.Contains(",");return v;
                    }
                }
            }
            throw new InvalidOperationException("Field copy unavailable. Use recipe.");
        }
        public double Read(string key) {
            SelectField(key);double v=CopyValue(key);Guard(key);Native.Press(0x0D);Thread.Sleep(70);return v;
        }
        public void Write(string key,double value) {
            Model.Check(Model.Find(key),value);SelectField(key);
            CopyValue(key); // Re-prove numeric focus before any text replacement.
            string number=Model.Number(value);
            if(comma.ContainsKey(key)&&comma[key]) number=number.Replace('.',',');
            Guard(key);Native.Type(number);Thread.Sleep(70);Guard(key);Native.Press(0x0D);Thread.Sleep(100);
        }
    }
}
