using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using VoiceMacro;

sealed class Fake : IFieldAccess {
    public Dictionary<string,double> Values=new Dictionary<string,double>{{"body",0},{"mud",0},{"presence",0},{"air",0},{"threshold",-18},{"ratio",1},{"makeup",0}};
    public List<string> Writes=new List<string>();
    public bool RejectFocus,RejectRead,IgnoreWrite;
    public int FailWriteAt=-1;
    public bool AliasBodyMud;
    public void Validate(string[] keys){if(RejectFocus)throw new InvalidOperationException("focus lost");foreach(string k in keys)if(!Values.ContainsKey(k))throw new InvalidOperationException("missing mapping");}
    public double Read(string key){if(RejectRead)throw new InvalidOperationException("clipboard unsupported");return Values[AliasBodyMud&&key=="mud"?"body":key];}
    public void Write(string key,double value){Writes.Add(key);if(Writes.Count==FailWriteAt)throw new InvalidOperationException("write interrupted");if(!IgnoreWrite)Values[AliasBodyMud&&key=="mud"?"body":key]=value;}
}
static class Tests {
    static int count;
    static void Check(string name,Action test){test();count++;Console.WriteLine("PASS "+name);}
    static void Assert(bool condition){if(!condition)throw new Exception("Assertion failed");}
    static void Throws(Action a){try{a();}catch{return;}throw new Exception("Exception expected");}
    public static int Main() {
        try {
            Check("Reject nonfinite and invalid presets",delegate{
                foreach(double x in new[]{Double.NaN,Double.PositiveInfinity,-1,101})Throws(delegate{Model.Map(new Preset{depth=x});});
                Throws(delegate{Model.Map(new Preset{schema=2});});
                Throws(delegate{Model.Map(new Preset{name=""});});
            });
            Check("Zero knobs remove macro gains",delegate{
                var v=Model.Map(new Preset{depth=0,presence=0,control=0});
                Assert(new[]{"body","mud","presence","air","makeup"}.All(k=>v[k]==0));Assert(v["ratio"]==1);
            });
            Check("Knob domains stay bounded",delegate{
                var r=new Random(13);
                for(int i=0;i<10000;i++){
                    var v=Model.Map(new Preset{depth=r.NextDouble()*100,presence=r.NextDouble()*100,control=r.NextDouble()*100});
                    Assert(v["body"]>=0&&v["body"]<=3.5&&v["mud"]>=-2.5&&v["mud"]<=0&&v["presence"]<=2.5&&v["air"]<=1&&v["makeup"]<=3&&v["ratio"]>=1&&v["ratio"]<=3.5&&v["threshold"]>=-26&&v["threshold"]<=-18);
                }
            });
            Check("Independent knob domains",delegate{
                var baseV=Model.Map(new Preset{depth=0,presence=0,control=0});
                var d=Model.Map(new Preset{depth=100,presence=0,control=0});
                var p=Model.Map(new Preset{depth=0,presence=100,control=0});
                var c=Model.Map(new Preset{depth=0,presence=0,control=100});
                Assert(new[]{"presence","air","threshold","ratio","makeup"}.All(k=>d[k]==baseV[k]));
                Assert(new[]{"body","mud","threshold","ratio","makeup"}.All(k=>p[k]==baseV[k]));
                Assert(new[]{"body","mud","presence","air"}.All(k=>c[k]==baseV[k]));
            });
            Check("Monotonic controls across travel",delegate{
                var old=Model.Map(new Preset{depth=0,presence=0,control=0});
                for(int i=1;i<=100;i++){
                    var n=Model.Map(new Preset{depth=i,presence=i,control=i});
                    Assert(n["body"]>=old["body"]&&n["mud"]<=old["mud"]&&n["presence"]>=old["presence"]&&n["air"]>=old["air"]&&n["ratio"]>=old["ratio"]&&n["threshold"]<=old["threshold"]);old=n;
                }
            });
            Check("Parse Resolve units and decimals",delegate{
                Assert(Model.Parse("-2,5 dB",Model.Find("body"))==-2.5);
                Assert(Model.Parse("\u221218.0 dBFS",Model.Find("threshold"))==-18);
                Assert(Model.Parse("2.5 : 1",Model.Find("ratio"))==2.5);
                Assert(Model.Parse("1:1",Model.Find("ratio"))==1);
            });
            Check("Reject ambiguous clipboard text",delegate{
                foreach(string s in new[]{"Track 2", "1:2", "NaN", "2.5:1:1", "999", "", "2\n3", "1e2"})Throws(delegate{Model.Parse(s,Model.Find("ratio"));});
                Throws(delegate{Model.Parse("30 dB",Model.Find("body"));});
            });
            Check("Missing mapping prevents writes",delegate{
                var f=new Fake();f.Values.Remove("ratio");Throws(delegate{Engine.Apply(f,Model.Map(new Preset()),delegate{});});Assert(f.Writes.Count==0);
            });
            Check("Focus rejection prevents writes",delegate{
                var f=new Fake{RejectFocus=true};Throws(delegate{Engine.Apply(f,Model.Map(new Preset()),delegate{});});Assert(f.Writes.Count==0);
            });
            Check("Clipboard rejection prevents writes",delegate{
                var f=new Fake{RejectRead=true};Throws(delegate{Engine.Apply(f,Model.Map(new Preset()),delegate{});});Assert(f.Writes.Count==0);
            });
            Check("Backup failure prevents writes",delegate{
                var f=new Fake();Throws(delegate{Engine.Apply(f,Model.Map(new Preset()),delegate{throw new IOException("disk full");});});Assert(f.Writes.Count==0);
            });
            Check("Backup precedes writes",delegate{
                var f=new Fake();bool backup=false;var target=Model.Map(new Preset());
                var before=Engine.Apply(f,target,delegate(Dictionary<string,double> values){Assert(f.Writes.Count==0);Assert(values["body"]==0);backup=true;});
                Assert(backup&&before["body"]==0&&target.All(p=>f.Values[p.Key]==p.Value));
            });
            Check("Readback mismatch stops writes",delegate{
                var f=new Fake{IgnoreWrite=true};Throws(delegate{Engine.Apply(f,Model.Map(new Preset()),delegate{});});Assert(f.Writes.Count==1);
            });
            Check("Final readback detects field aliasing",delegate{
                var f=new Fake{AliasBodyMud=true};Throws(delegate{Engine.Apply(f,Model.Map(new Preset()),delegate{});});
            });
            Check("Interrupted batch preserves recovery data",delegate{
                var f=new Fake{FailWriteAt=2};Dictionary<string,double> backup=null;
                try{Engine.Apply(f,Model.Map(new Preset()),delegate(Dictionary<string,double> v){backup=v;});throw new Exception("Must fail");}
                catch(ApplyFailure e){Assert(e.Attempted.Count==2&&backup["body"]==0&&f.Writes.Count==2);}
            });
            Check("Unchanged values produce no writes",delegate{
                var f=new Fake();Engine.Apply(f,new Dictionary<string,double>(f.Values),delegate{});Assert(f.Writes.Count==0);
            });
            Check("Restore recovers earlier values",delegate{
                var f=new Fake();var original=new Dictionary<string,double>(f.Values);
                var before=Engine.Apply(f,Model.Map(new Preset()),delegate{});Engine.Apply(f,before,delegate{});Assert(original.All(p=>f.Values[p.Key]==p.Value));
            });
            Check("Group updates preserve unrelated fields",delegate{
                var f=new Fake();Engine.Apply(f,new Dictionary<string,double>{{"body",2}},delegate{});Assert(f.Writes.SequenceEqual(new[]{"body"})&&f.Values["ratio"]==1);
            });
            Check("Invalid targets fail before mutation",delegate{
                var f=new Fake();Throws(delegate{Engine.Apply(f,new Dictionary<string,double>{{"body",99}},delegate{});});Throws(delegate{Engine.Apply(f,new Dictionary<string,double>{{"unknown",1}},delegate{});});Assert(f.Writes.Count==0);
            });
            Check("Preset roundtrip and replacement",delegate{
                string p=Path.Combine(Path.GetTempPath(),Guid.NewGuid()+".json");
                try{JsonFile.Write(p,new Preset{depth=17,name="Test"});var v=JsonFile.Read<Preset>(p);v.Validate();Assert(v.depth==17);v.depth=82;JsonFile.Write(p,v);Assert(JsonFile.Read<Preset>(p).depth==82);}finally{File.Delete(p);}
            });
            Check("Truncated preset is rejected",delegate{
                string p=Path.Combine(Path.GetTempPath(),Guid.NewGuid()+".json");
                try{File.WriteAllText(p,"{\"schema\":1}");Throws(delegate{JsonFile.Read<Preset>(p);});}finally{File.Delete(p);}
            });
            Check("Recipe marks fixed processing",delegate{string s=Model.Recipe(new Preset());Assert(s.Contains("Zeros retain the high-pass filter.")&&s.Contains("Disable Band 6.")&&s.Contains("Knee uses Resolve's scale."));});
            Check("Reject duplicate mapped coordinates",delegate{
                var l=new Layout{fields=new List<Binding>{
                    new Binding{key="body",title="EQ - Voice",width=800,height=400,x=20,y=30,dpi=96},
                    new Binding{key="mud",title="EQ - Voice",width=800,height=400,x=21,y=31,dpi=96}}};
                Throws(delegate{l.Validate();});
            });
            Check("Reject mixed tracks within EQ",delegate{
                var l=new Layout{fields=new List<Binding>{
                    new Binding{key="body",title="EQ - Voice",width=800,height=400,x=20,y=30,dpi=96},
                    new Binding{key="mud",title="EQ - Music",width=800,height=400,x=60,y=30,dpi=96}}};
                Throws(delegate{l.Validate();});
            });
            Check("Reject off-window calibration",delegate{
                var l=new Layout{fields=new List<Binding>{new Binding{key="body",title="EQ",width=800,height=400,x=800,y=30,dpi=96}}};
                Throws(delegate{l.Validate();});
            });
            Check("Accept separate EQ and dynamics",delegate{
                var l=new Layout{fields=new List<Binding>{
                    new Binding{key="body",title="EQ - Voice",width=800,height=400,x=20,y=30,dpi=96},
                    new Binding{key="ratio",title="Dynamics - Voice",width=800,height=400,x=20,y=30,dpi=96}}};
                l.Validate();
            });
            Console.WriteLine(count+" TEST GROUPS PASSED");Console.WriteLine("Windows and Resolve integration: NOT TESTED HERE");return 0;
        }catch(Exception e){Console.Error.WriteLine(e);return 1;}
    }
}
