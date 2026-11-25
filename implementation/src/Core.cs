using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;
using System.Text.RegularExpressions;

namespace VoiceMacro {
    [DataContract]
    public sealed class Binding {
        [DataMember(IsRequired=true)] public string key;
        [DataMember(IsRequired=true)] public string title;
        [DataMember(IsRequired=true)] public int width,height,x,y,dpi;
    }
    [DataContract]
    public sealed class Layout {
        [DataMember(IsRequired=true)] public int schema=1;
        [DataMember(IsRequired=true)] public string id=Guid.NewGuid().ToString("N");
        [DataMember(IsRequired=true)] public List<Binding> fields=new List<Binding>();
        public void Validate() {
            if(schema!=1 || fields==null || fields.Count>7 || String.IsNullOrEmpty(id)) throw new InvalidDataException("Layout format unsupported.");
            var keys=new HashSet<string>();
            foreach(var b in fields) {
                Model.Find(b.key);
                if(!keys.Add(b.key) || String.IsNullOrEmpty(b.title) || b.title.Length>512 || b.width<1 || b.height<1 ||
                    b.x<0||b.y<0||b.x>=b.width||b.y>=b.height||b.dpi<72||b.dpi>768)
                    throw new InvalidDataException("Layout field invalid.");
            }
            for(int i=0;i<fields.Count;i++)for(int j=i+1;j<fields.Count;j++) {
                var a=fields[i];var b=fields[j];
                if(a.title==b.title && Math.Abs(a.x-b.x)<6 && Math.Abs(a.y-b.y)<6)
                    throw new InvalidDataException("Two fields share one position.");
                if(Model.Find(a.key).Group==Model.Find(b.key).Group && a.title!=b.title)
                    throw new InvalidDataException("Map each group within one window.");
            }
        }
    }
    public sealed class Field {
        public string Key, Group, Label;
        public double Min, Max;
        public Field(string key, string group, string label, double min, double max) {
            Key=key; Group=group; Label=label; Min=min; Max=max;
        }
    }
    [DataContract]
    public sealed class Preset {
        [DataMember(IsRequired=true)] public int schema=1;
        [DataMember(IsRequired=true)] public string name="Voice";
        [DataMember(IsRequired=true)] public double depth=35;
        [DataMember(IsRequired=true)] public double presence=25;
        [DataMember(IsRequired=true)] public double control=30;
        public void Validate() {
            if(schema!=1) throw new InvalidDataException("Preset version unsupported.");
            if(String.IsNullOrWhiteSpace(name) || name.Length>100) throw new InvalidDataException("Preset name invalid.");
            foreach(double v in new[]{depth,presence,control})
                if(Double.IsNaN(v)||Double.IsInfinity(v)||v<0||v>100) throw new InvalidDataException("Knobs require 0 through 100.");
        }
        public Preset Clone() { return new Preset{name=name,depth=depth,presence=presence,control=control}; }
    }
    public static class Model {
        public static readonly Field[] Fields = {
            new Field("body", "EQ", "Band 2: Gain", -20,20),
            new Field("mud", "EQ", "Band 3: Gain", -20,20),
            new Field("presence", "EQ", "Band 4: Gain", -20,20),
            new Field("air", "EQ", "Band 5: Gain", -20,20),
            new Field("threshold", "Dynamics", "Compressor: Threshold", -60,0),
            new Field("ratio", "Dynamics", "Compressor: Ratio", 1,20),
            new Field("makeup", "Dynamics", "Dynamics: Make Up", -20,20)
        };
        public static Field Find(string key) {
            Field f=Fields.FirstOrDefault(x=>x.Key==key);
            if(f==null) throw new InvalidDataException("Field unknown.");
            return f;
        }
        public static double Round(double x) { return Math.Round(x,1,MidpointRounding.AwayFromZero); }
        public static Dictionary<string,double> Map(Preset p) {
            p.Validate(); double d=p.depth/100,pres=p.presence/100,c=p.control/100;
            return new Dictionary<string,double> {
                {"body",Round(3.5*d)}, {"mud",Round(-2.5*d)},
                {"presence",Round(2.5*pres)}, {"air",Round(pres*pres)},
                {"threshold",Round(-18-8*c)}, {"ratio",Round(1+2.5*c)},
                {"makeup",Round(3*c)}
            };
        }
        public static string Number(double x) { return x.ToString("0.0",CultureInfo.InvariantCulture); }
        public static double Parse(string text, Field field) {
            if(text==null || text.Length>60) throw new InvalidDataException("Cannot read field value.");
            string s=text.Trim().Replace('\u2212','-').Replace(',','.');
            string pattern=field.Key=="ratio" ? @"^([+-]?\d+(?:\.\d+)?)\s*(?::\s*1(?:\.0+)?)?$" : @"^([+-]?\d+(?:\.\d+)?)\s*(?:dB(?:FS)?)?$";
            Match m=Regex.Match(s,pattern,RegexOptions.IgnoreCase);
            double value;
            if(!m.Success || !Double.TryParse(m.Groups[1].Value,NumberStyles.Float,CultureInfo.InvariantCulture,out value))
                throw new InvalidDataException("Field cannot be read: "+field.Label);
            Check(field,value); return value;
        }
        public static void Check(Field f,double x) {
            if(Double.IsNaN(x)||Double.IsInfinity(x)||x<f.Min||x>f.Max)
                throw new InvalidDataException("Value outside field range: "+f.Label);
        }
        public static string Recipe(Preset p) {
            var v=Map(p); var b=new StringBuilder();
            b.AppendLine("VOICE MACRO / "+p.name);
            b.AppendLine("Depth "+Number(p.depth)+" / Presence "+Number(p.presence)+" / Control "+Number(p.control));
            b.AppendLine(); b.AppendLine("SETUP ONCE / TRACK EQ");
            b.AppendLine("Enable EQ. Select Earth type.");
            b.AppendLine("Enable Bands 1 through 5.");
            b.AppendLine("Band 1: high-pass, 70 Hz.");
            b.AppendLine("Slope: 12 dB/octave.");
            b.AppendLine("Band 2: bell, 140 Hz."); b.AppendLine("Q: 0.8.");
            b.AppendLine("Band 3: bell, 320 Hz."); b.AppendLine("Q: 1.0.");
            b.AppendLine("Band 4: bell, 3200 Hz."); b.AppendLine("Q: 1.0.");
            b.AppendLine("Band 5: shelf, 10000 Hz."); b.AppendLine("Use high-shelf. Q: 0.7.");
            b.AppendLine("Disable Band 6."); b.AppendLine("EQ output: 0 dB.");
            b.AppendLine(); b.AppendLine("SETUP ONCE / DYNAMICS");
            b.AppendLine("Enable Compressor."); b.AppendLine("Attack: 10 ms. Hold: 0.");
            b.AppendLine("Release: 120 ms. Knee: 20.");
            b.AppendLine("Knee uses Resolve's scale.");
            b.AppendLine("Mix: 0. Sidechain: off.");
            b.AppendLine("Disable Expander, Gate, and Limiter.");
            b.AppendLine("Prepare speech peaks around -12dBFS.");
            b.AppendLine("Check output peaks after changes.");
            b.AppendLine(); b.AppendLine("KNOB VALUES / APPLY THESE");
            foreach(var f in Fields) b.AppendLine(f.Group+" / "+f.Label+": "+Number(v[f.Key])+(f.Key=="ratio"?":1":" dB"));
            b.AppendLine(); b.AppendLine("Zeros retain the high-pass filter.");
            b.AppendLine("Settings require listening and adjustment.");
            b.AppendLine("Output loudness remains your decision.");
            return b.ToString();
        }
    }
    public static class JsonFile {
        public static T Read<T>(string path) {
            if(new FileInfo(path).Length>1024*1024) throw new InvalidDataException("File exceeds size limit.");
            using(var s=File.OpenRead(path)) return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(s);
        }
        public static void Write<T>(string path,T item) {
            string dir=Path.GetDirectoryName(Path.GetFullPath(path)); Directory.CreateDirectory(dir);
            string temp=Path.Combine(dir,Guid.NewGuid().ToString("N")+".tmp");
            try {
                using(var s=File.Create(temp)) new DataContractJsonSerializer(typeof(T)).WriteObject(s,item);
                if(File.Exists(path)) File.Replace(temp,path,null); else File.Move(temp,path);
            } finally { if(File.Exists(temp)) File.Delete(temp); }
        }
    }
    public interface IFieldAccess {
        void Validate(string[] keys);
        double Read(string key);
        void Write(string key,double value);
    }
    [DataContract]
    public sealed class Snapshot {
        [DataMember] public string time;
        [DataMember] public Dictionary<string,double> values;
        [DataMember] public string layoutId;
    }
    public sealed class ApplyFailure:Exception {
        public readonly List<string> Attempted;
        public ApplyFailure(string message,List<string> attempted,Exception inner):base(message,inner) { Attempted=attempted; }
    }
    public static class Engine {
        public static Dictionary<string,double> ReadAll(IFieldAccess access,string[] keys) {
            access.Validate(keys); var result=new Dictionary<string,double>();
            foreach(string key in keys) {double n=access.Read(key);Model.Check(Model.Find(key),n);result.Add(key,n);}
            return result;
        }
        public static Dictionary<string,double> Apply(IFieldAccess access,Dictionary<string,double> values,Action<Dictionary<string,double>> backup) {
            if(values==null || values.Count==0) throw new InvalidDataException("No values selected.");
            foreach(var p in values) Model.Check(Model.Find(p.Key),p.Value);
            var keys=Model.Fields.Where(f=>values.ContainsKey(f.Key)).Select(f=>f.Key).ToArray();
            var before=ReadAll(access,keys);
            backup(new Dictionary<string,double>(before)); // Persist before the first write.
            var attempted=new List<string>();
            try {
                foreach(string key in keys) {
                    if(Math.Abs(before[key]-values[key])<0.051) continue;
                    access.Validate(keys); attempted.Add(key);
                    access.Write(key,values[key]);
                    double read=access.Read(key);
                    if(Math.Abs(read-values[key])>0.11) throw new InvalidDataException("Readback differs: "+Model.Find(key).Label);
                }
                // Detect aliased mappings and changes introduced by later writes.
                var final=ReadAll(access,keys);
                foreach(string key in keys)
                    if(Math.Abs(final[key]-values[key])>0.11) throw new InvalidDataException("Final readback differs: "+Model.Find(key).Label);
                return before;
            } catch(Exception e) {
                throw new ApplyFailure("Stopped. Some fields may differ.\nInspect values before restoring.",attempted,e);
            }
        }
    }
}
