import time, subprocess, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FB = "/dev/fb0"
W, H = 320, 240
FPS = 20
DATA_INTERVAL = 1.0
SMOOTH = 0.15            # 进度条平滑
THEME_SPEED = 0.04      # 主题过渡速度(越小过渡越慢越柔)

# ---------- 字体 ----------
def font(sz, bold=False):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else "")
    try: return ImageFont.truetype(p, sz)
    except: return ImageFont.load_default()
F_IP=font(30,True); F_LBL=font(13); F_TIME=font(20,True); F_BAR=font(13,True)

# ---------- 数据 ----------
def get_ip():
    out=subprocess.run(["hostname","-I"],capture_output=True,text=True).stdout
    for t in out.split():
        if t.count(".")==3: return t
    return "no-ip"
_prev=[0,0]
def get_cpu():
    with open("/proc/stat") as f: nums=list(map(int,f.readline().split()[1:]))
    idle=nums[3]+nums[4]; total=sum(nums)
    dt=total-_prev[0]; di=idle-_prev[1]; _prev[0],_prev[1]=total,idle
    return 0.0 if dt<=0 else max(0,min(100,(1-di/dt)*100))
def get_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f: return int(f.read())/1000.0
    except: return 0.0
def get_mem():
    d={}
    with open("/proc/meminfo") as f:
        for line in f: d[line.split(":")[0]]=int(line.split()[1])
    return (1-d["MemAvailable"]/d["MemTotal"])*100, d["MemTotal"]/1024/1024

# ---------- 两套主题(日间 / 夜间) ----------
DAY = dict(bg=(28,36,58), track=(55,65,90), accent=(70,160,255),
           white=(245,248,255), grey=(150,165,195), mem=(150,120,255))
NIGHT = dict(bg=(8,10,20), track=(28,32,48), accent=(60,110,180),
             white=(190,200,220), grey=(90,100,130), mem=(110,90,180))

def lerp(a,b,f): return tuple(int(a[i]+(b[i]-a[i])*f) for i in range(3))
def theme(mix, key): return lerp(DAY[key], NIGHT[key], mix)

def temp_color(t, mix):
    t=max(35,min(75,t))
    if t<55: f=(t-35)/20; day=(int(80+f*175),int(220-f*20),int(90-f*30))
    else: f=(t-55)/20; day=(255,int(200-f*180),int(60-f*30))
    return lerp(day, lerp(day,(60,60,80),0.4), mix)  # 夜间稍微压暗

# ---------- 进度条 ----------
def bar(d,x,y,w,h,frac,color,track,label,val,grey):
    d.text((x,y-18),label,font=F_LBL,fill=grey)
    d.text((x+w-70,y-18),val,font=F_BAR,fill=color)
    r=h//2; d.rounded_rectangle([x,y,x+w,y+h],radius=r,fill=track)
    fw=int(w*max(0,min(1,frac)))
    if fw>=h: d.rounded_rectangle([x,y,x+fw,y+h],radius=r,fill=color)
    elif fw>0: d.ellipse([x,y,x+h,y+h],fill=color)

# ---------- 太阳/月亮天体 ----------
def draw_celestial(d, cx, cy, mix, t):
    sun_a = 1-mix     # 太阳强度
    moon_a = mix      # 月亮强度
    body = lerp((255,210,80),(220,230,255), mix)   # 暖黄->冷白
    # 太阳光芒(旋转+呼吸),仅日间显示
    if sun_a>0.02:
        rot=t*0.6
        breathe=1+0.12*math.sin(t*2)
        for i in range(8):
            ang=rot+i*math.pi/4
            r1=10*breathe; r2=15*breathe
            x1=cx+math.cos(ang)*r1; y1=cy+math.sin(ang)*r1
            x2=cx+math.cos(ang)*r2; y2=cy+math.sin(ang)*r2
            col=tuple(int(c*sun_a) for c in (255,200,90))
            d.line([x1,y1,x2,y2],fill=col,width=2)
    # 浮动(夜间月亮轻微上下浮)
    fy=cy+math.sin(t*1.2)*1.5*moon_a
    # 主体圆
    R=7
    d.ellipse([cx-R,fy-R,cx+R,fy+R],fill=body)
    # 月亮缺口(夜间渐显):用背景色画个偏移的圆挖出弯月
    if moon_a>0.02:
        bg=theme(mix,"bg")
        notch=tuple(int(bg[i]*moon_a+body[i]*(1-moon_a)) for i in range(3))
        d.ellipse([cx-R+4,fy-R-1,cx+R+4,fy+R-1],fill=notch)
    # 夜间小星星(闪烁)
    if moon_a>0.3:
        for sx,sy,ph in [(-14,-6,0),(-10,8,1.5),(12,10,3)]:
            tw=(0.5+0.5*math.sin(t*3+ph))*moon_a
            c=tuple(int(200*tw) for _ in range(3))
            d.ellipse([cx+sx-1,fy+sy-1,cx+sx+1,fy+sy+1],fill=(c[0],c[1],min(255,c[2]+40)))

# ---------- framebuffer ----------
def push(img):
    arr=np.array(img,dtype=np.uint8)
    out=np.zeros((H,W,4),dtype=np.uint8)
    out[...,0]=arr[...,2]; out[...,1]=arr[...,1]; out[...,2]=arr[...,0]
    with open(FB,"wb") as f: f.write(out.tobytes())

# ---------- 主循环 ----------
disp={"cpu":0,"temp":0,"mem":0}
get_cpu()
data={"ip":get_ip(),"cpu":0,"temp":0,"mem":0,"memgb":0}
last=0
theme_mix = 1.0 if not (6<=time.localtime().tm_hour<18) else 0.0  # 启动即正确
anim=0.0

while True:
    now=time.time()
    if now-last>=DATA_INTERVAL:
        data["ip"]=get_ip(); data["cpu"]=get_cpu()
        data["temp"]=get_temp(); data["mem"],data["memgb"]=get_mem()
        last=now
    for k in("cpu","temp","mem"): disp[k]+=(data[k]-disp[k])*SMOOTH

    # 主题目标 & 平滑过渡
    is_day = 6<=time.localtime().tm_hour<18
    target = 0.0 if is_day else 1.0
    theme_mix += (target-theme_mix)*THEME_SPEED
    m=theme_mix
    anim+=1.0/FPS

    bg=theme(m,"bg"); track=theme(m,"track"); accent=theme(m,"accent")
    white=theme(m,"white"); grey=theme(m,"grey"); memc=theme(m,"mem")

    img=Image.new("RGB",(W,H),bg); d=ImageDraw.Draw(img)
    d.rectangle([0,0,W,4],fill=accent)
    d.text((16,16),"IP ADDRESS",font=F_LBL,fill=accent)
    d.text((16,32),data["ip"],font=F_IP,fill=white)
    d.text((16,76),time.strftime("%H:%M:%S"),font=F_TIME,fill=grey)
    draw_celestial(d, W-26, 22, m, anim)
    d.line([16,108,W-16,108],fill=track,width=1)

    bx,bw,bh=16,W-32,16
    bar(d,bx,130,bw,bh,disp["cpu"]/100,accent,track,"CPU",f"{disp['cpu']:.0f}%",grey)
    bar(d,bx,172,bw,bh,(disp["temp"]-30)/50,temp_color(disp["temp"],m),track,"TEMP",f"{disp['temp']:.1f}\u00b0C",grey)
    bar(d,bx,214,bw,bh,disp["mem"]/100,memc,track,"MEM",f"{disp['mem']:.0f}% {data['memgb']:.1f}G",grey)

    push(img)
    time.sleep(1.0/FPS)