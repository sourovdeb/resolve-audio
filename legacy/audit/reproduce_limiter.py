from pathlib import Path
import sys, subprocess, numpy as np
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'legacy/obs/tools'))
from render_matched import limit_exact, encode
n=96000; t=np.arange(n)/48000
x=1.2*np.sin(2*np.pi*12000*t+np.pi/4)
x*=np.minimum(1,np.minimum(np.arange(n),np.arange(n)[::-1])/2400)
y,_=limit_exact(x[None,:]); out=root/'audit/limiter-counterexample.wav'
encode(out,y,48000)
print('sample peak dBFS:',20*np.log10(np.max(abs(y))))
r=subprocess.run(['ffmpeg','-hide_banner','-i',str(out),'-af','ebur128=peak=true','-f','null','-'],capture_output=True,text=True,check=True)
print(r.stderr.split('Summary:')[-1])
