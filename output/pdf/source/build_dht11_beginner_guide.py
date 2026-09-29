from pathlib import Path
import math
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.enums import TA_LEFT

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "output/pdf/ESP32_DHT11_零基础硬件操作手册.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)
pdfmetrics.registerFont(TTFont("CN", "/System/Library/Fonts/STHeiti Light.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("CNB", "/System/Library/Fonts/STHeiti Medium.ttc", subfontIndex=0))
pdfmetrics.registerFontFamily("CN", normal="CN", bold="CNB", italic="CN", boldItalic="CNB")
W, H = 595.276, 841.89
M, CW = 43, W-86
NAVY, TEAL, MUTED = map(HexColor, ["#17354B", "#007F83", "#5A6E7C"])
PALE, LINE, AMBER, RED = map(HexColor, ["#F0F6F7", "#D9E3E8", "#9B5B10", "#AD3A36"])
TOTAL = 22
c = canvas.Canvas(str(OUT), pagesize=(W,H), pageCompression=1)
c.setTitle("ESP32 + DHT11 零基础硬件操作手册")
c.setAuthor("芯鉴知微项目")
c.setSubject("从认器材、接线、烧录到采集、异常恢复和记录；操作指导稿，固件0.2.5；现场环境和硬件待核验")
c.setViewerPreference("DisplayDocTitle", "true")
page_no = 0
TEXTS = []

def p(text, y, x=M, w=CW, size=11.5, leading=18, color=NAVY, bold=False):
    TEXTS.append(text)
    st=ParagraphStyle("p", fontName="CNB" if bold else "CN", fontSize=size,
                      leading=leading, textColor=color, wordWrap="CJK", splitLongWords=1,
                      spaceAfter=0, allowWidows=0, allowOrphans=0)
    obj=Paragraph(text, st)
    aw,ah=obj.wrap(w,1000)
    if y+ah>786:
        raise RuntimeError(f"page {page_no} overflow at {y+ah}: {text[:60]}")
    obj.drawOn(c,x,H-y-ah)
    return y+ah

def label(text,x,y,size=10,color=MUTED,bold=False):
    c.setFillColor(color);c.setFont("CNB" if bold else "CN",size)
    c.drawString(x,H-y-size,text)
    TEXTS.append(text)

def rect(x,y,w,h,fill=PALE,stroke=None,r=9):
    c.setFillColor(fill)
    c.setStrokeColor(stroke or fill)
    c.roundRect(x,H-y-h,w,h,r,stroke=int(stroke is not None),fill=1)

def ln(x1,y1,x2,y2,color=LINE,width=1,dash=None):
    c.setStrokeColor(color);c.setLineWidth(width)
    c.setDash(dash or [])
    c.line(x1,H-y1,x2,H-y2);c.setDash([])

def page(title,sub,part="现场操作"):
    global page_no
    if page_no: c.showPage()
    page_no+=1
    c.bookmarkPage(f"p{page_no}")
    c.addOutlineEntry(title,f"p{page_no}",0,False)
    label("芯鉴知微  /  ESP32 + DHT11",M,25,9,TEAL,True)
    c.setFont("CN",9);c.setFillColor(MUTED)
    c.drawRightString(W-M,H-34,part)
    p(title,62,size=24,leading=31,bold=True)
    p(sub,104,size=10.5,leading=16,color=MUTED)
    ln(M,790,W-M,790)
    label("操作版 v2 · 2026-09-29 · 实际结果请现场填写",M,802,8.2)
    c.setFont("CN",9);c.drawRightString(W-M, H-812, f"{page_no:02d} / {TOTAL}")

def note(title,body,y,kind="info"):
    color=TEAL if kind=="info" else AMBER if kind=="wait" else RED
    bg=HexColor("#EDF7F6") if kind=="info" else HexColor("#FFF5E5") if kind=="wait" else HexColor("#FCEFED")
    st=ParagraphStyle("n",fontName="CN",fontSize=11,leading=17,wordWrap="CJK")
    ph=Paragraph(body,st).wrap(CW-30,1000)[1]
    height=ph+48
    rect(M,y,CW,height,bg)
    p(title,y+12,x=M+15,w=CW-30,size=12,leading=18,color=color,bold=True)
    p(body,y+35,x=M+15,w=CW-30,size=11,leading=17)
    return y+height+16

def step(num,title,body,y):
    c.setFillColor(TEAL);c.circle(M+13,H-y-13,13,stroke=0,fill=1)
    c.setFillColor(white);c.setFont("CNB",11)
    c.drawCentredString(M+13,H-y-17,str(num))
    yy=p(title,y,x=M+39,w=CW-39,size=13,leading=19,bold=True)
    yy=p(body,yy+6,x=M+39,w=CW-39)
    return yy+19

def check(text,y):
    c.setStrokeColor(TEAL);c.setLineWidth(1)
    c.rect(M+2,H-y-13,11,11,stroke=1,fill=0)
    return p(text,y,x=M+25,w=CW-25,size=11,leading=17)+13

def code(lines,y,caption=None):
    arr=lines.splitlines()
    h=len(arr)*15+26+(21 if caption else 0)
    rect(M,y,CW,h,HexColor("#F2F4F6"))
    if caption: label(caption,M+13,y+10,10,TEAL,True)
    yy=y+14+(21 if caption else 0)
    for line in arr:
        if pdfmetrics.stringWidth(line,"Courier",9.1)>CW-26:
            raise RuntimeError(f"long code line: {line}")
        c.setFillColor(NAVY);c.setFont("Courier",9.1)
        c.drawString(M+13,H-yy-9.1,line);yy+=15
        TEXTS.append(line)
    return y+h+15

def table(headers,rows,y,widths=None,size=10.5,pad=9):
    widths=widths or [CW/len(headers)]*len(headers)
    st=ParagraphStyle("t",fontName="CN",fontSize=size,leading=size+5,
                      wordWrap="CJK",textColor=NAVY,splitLongWords=1)
    hs=ParagraphStyle("th",parent=st,fontName="CNB",textColor=white)
    data=[[Paragraph(str(x),hs) for x in headers]]+[[Paragraph(str(x),st) for x in row] for row in rows]
    for row in [headers]+rows: TEXTS.extend(map(str,row))
    t=Table(data,colWidths=widths,hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),TEAL),("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),pad),("RIGHTPADDING",(0,0),(-1,-1),pad),
        ("TOPPADDING",(0,0),(-1,-1),pad),("BOTTOMPADDING",(0,0),(-1,-1),pad),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[white,PALE]),
        ("LINEBELOW",(0,0),(-1,0),.5,TEAL),
        ("LINEBELOW",(0,1),(-1,-1),.5,LINE)
    ]))
    tw,th=t.wrap(CW,1000)
    if y+th>782:raise RuntimeError(f"table overflow p{page_no}: {y+th}")
    t.drawOn(c,M,H-y-th)
    return y+th+17

def dht(x,y,scale=1,numbers=True):
    bw,bh=100*scale,118*scale
    rect(x,y,bw,bh,HexColor("#238BC1"),r=7*scale)
    for row in range(5):
        for col in range(4):
            rect(x+(12+col*22)*scale,y+(12+row*20)*scale,11*scale,10*scale,HexColor("#135476"),r=2)
    pins=[]
    for i in range(4):
        px=x+(17+i*22)*scale
        ln(px,y+bh,px,y+bh+38*scale,HexColor("#84939C"),3*scale)
        pins.append((px,y+bh+38*scale))
        if numbers:label(str(i+1),px-4,y+bh+42*scale,12*scale,NAVY,True)
    return pins

def board_icon(x,y,w=130,h=160):
    rect(x,y,w,h,HexColor("#26444D"),r=8)
    rect(x+20,y+16,w-40,55,HexColor("#C9D4D8"),r=2)
    p("ESP32",y+29,x=x+22,w=w-44,size=15,leading=20,bold=True)
    rect(x+w/2-18,y+h-15,36,23,HexColor("#ADB8BD"),r=3)
    for i in range(8):
        for px in (x+6,x+w-10):rect(px,y+18+i*16,4,6,HexColor("#D2B16D"),r=1)
    return

# 01
page("从接线到看到温湿度","零基础硬件操作手册 · 按页操作，看到预期结果再继续","实验指导稿")
rect(M,155,CW,248,PALE)
board_icon(93,190,120,160);dht(352,188,1.0)
ln(213,240,292,240,TEAL,3);ln(292,240,340,260,TEAL,3)
p("ESP32 开发板",367,x=83,w=160,size=12,bold=True)
p("DHT11 传感器",367,x=325,w=180,size=12,bold=True)
y=p("你最终要完成什么？",432,size=18,leading=24,bold=True)
y=p("把传感器接到开发板，看到真实温湿度，把数据送到平台，再试一次“断开信号线、重新接好”和断网恢复。每一步都留下记录。",y+12,size=13,leading=22)
y=note("使用前先看第 2 页","固件 0.2.5 已修复采样计时与 HTTPS 配置问题，相关主机回归通过。实际电脑环境、接线和板卡仍需核对；先完成第 2 页的准备卡，再烧录和通电实验。",y+25,"wait")
p("适用：ESP32-DevKitC V4（WROOM-32E）+ 四针裸 DHT11。<br/>三针模块、ESP32-C3/S3 等其他硬件先核对，不能直接照接。",y,size=10.5,leading=17,color=MUTED)

# 02
page("先确认：现在能不能开工？","这一页由你和负责软件准备的人一起完成；软件准备也可以交给 Codex。","开工交接")
y=note("当前状态：程序已修复，现场准备待核对","本册对应资料包 2.0.11、固件 0.2.5。已补上慢网络、重启等待和 HTTPS 配置保护的测试；读数“过多久算旧数据”仍需实测后确定，不能提前判为硬件通过。",151,"wait")
y=p("你不用先学会数据库和接口。先拿到这张准备卡。",y+2,size=13,leading=20,bold=True)
for text in [
    "已核对使用修复版 0.2.5，并记录本次文件版本与指纹。",
    "已在烧录电脑上验证 PlatformIO 可用、项目能构建。",
    "已准备“本地采集版”（不填写网络和平台账号）。",
    "已确认初始化镜像适用于这块板的分区。",
    "开始第 12 页前：测试平台、账号、设备和任务已准备好。"
]:y=check(text,y+14)
y=table(["现场填写","记录"],[
    ["本次固件 / 资料包版本","____________________________"],
    ["项目文件夹 / 烧录电脑系统","____________________________"],
    ["确认人 / 日期","____________________________"]
],y+10,[190,CW-190])
p("今天可以先整理器材、认引脚、练习断电接线。准备项没有确认前，停在相应步骤，不用自己修改代码凑出“成功”。",y,size=11,leading=18)

# 03
page("把桌上的东西准备齐","先照着清单点一遍；不需要另外购买复杂仪器。")
y=table(["物品","你要确认的事"],[
    ["ESP32 开发板 × 1","板上模组写有 ESP32-WROOM-32E，板型与本册一致。"],
    ["四针 DHT11 × 1","蓝色网格外壳，底部 4 根脚；带小电路板的三针模块先停下核对。"],
    ["4.7kΩ 电阻 × 1","用来把信号线拉到 3.3V；不能用一根导线代替。"],
    ["面包板、短杜邦线","线头接触可靠；板卡不要把面包板插孔全部挡住。"],
    ["USB 数据线","要能传数据，只有充电功能的线不够。"],
    ["万用表","用来认电阻、查连通、测供电；第 7 页说明怎么用。"],
    ["电脑和实验 Wi-Fi","电脑可以同时负责烧录和运行平台，也可以分成两台。"]
],152,[155,CW-155])
y=note("两台电脑时，记住一个区别","USB 连接的是“烧录电脑”；开发板通过 Wi-Fi 找的是“平台电脑”。两台电脑可以不同，但平台地址必须填运行平台的那一台。",y)
p("可选：逻辑分析仪用于进一步检查信号时序；参考温湿度计用于后续精度比较。第一轮不凭房间里“看起来正常”的数字判定精度合格。",y,size=11,leading=18)

# 04
page("认引脚：先分清正面和背面","这一页只认位置；插线前先拔 USB。")
dht(91,168,1.12)
p("DHT11 正面",178,x=271,w=230,size=17,leading=24,bold=True)
p("让蓝色网格面朝向你，四根脚朝下。<br/>对本册所选的四针裸 DHT11，从左到右是 1、2、3、4。",220,x=271,w=230,size=12,leading=20)
p("方向依据：奥松 V1.3 手册图 1。<br/>外形或随货说明不一致时，先核对型号。",303,x=271,w=230,size=10.5,leading=17,color=MUTED)
y=table(["脚号","名称","用来做什么"],[
    ["1","VDD","接电源 3V3"],
    ["2","DATA","传送温湿度数据"],
    ["3","NC","空脚，留着不接"],
    ["4","GND","接地，也就是电路的公共回路"]
],395,[62,88,CW-150])
y=note("ESP32 上要找的是这些印字","找到 3V3、GND 和 IO4（有的板写 GPIO4）。GPIO4 不是“从某边数第 4 根针”。本册后面的连接图不表示实际排针位置。",y)
p("如果开发板上没有这些标识、传感器只有 3 根脚，先拍清楚标识，再让 Codex 核对，不靠猜。",y,size=11)

# 05
page("面包板：插在一起不等于接通","先理解哪几个孔内部相连，后面才不会“看起来接了，实际没接”。")
rect(M,155,CW,270,HexColor("#FAFBFC"),LINE)
label("同一行：A-E 内部相连",M+20,168,12,TEAL,True)
label("F-J 是另一组",M+280,168,12,TEAL,True)
x0=M+35; pitch=21
for i,ch in enumerate("ABCDEFGHIJ"):
    px=x0+i*pitch+(52 if i>=5 else 0)
    label(ch,px-3,200,9)
for row in range(5):
    yy=240+row*30
    if row==2:
        ln(x0,yy,x0+4*pitch,yy,TEAL,4)
        ln(x0+5*pitch+52,yy,x0+9*pitch+52,yy,HexColor("#DC9B44"),4)
    for i in range(10):
        px=x0+i*pitch+(52 if i>=5 else 0)
        c.setFillColor(white);c.setStrokeColor(MUTED)
        c.circle(px,H-yy,3.4,stroke=1,fill=1)
label("中间凹槽隔开两组",M+160,388,11,RED,True)
y=step(1,"让 4 根脚进入 4 个不同的连通组","如果把 DHT11 的 4 根脚插进同一行的 A、B、C、D，它们会被连在一起，不能通电。",451)
y=step(2,"信号线和电阻可以共享 DATA 所在的连通组","只要在同一组孔里，它们就接到了同一个点；要先确认孔的内部连接。",y)
y=step(3,"侧边电源轨可能在中间断开","红蓝线是标记，不是电源。先用断电连通检查确认，不确定时用短线直接连指定点。",y)
p("示意图只讲连通关系，不指定你实际插第几行。窄面包板放不下开发板时，可以把开发板放在旁边，用杜邦线连接。",y,size=10.5,leading=17,color=MUTED)

# 06
page("接线总图：只需要认这四个点","全程断电操作。线色方便辨认，但最终以两端标识为准。")
rect(M,155,CW,330,PALE)
rect(71,192,143,230,white,LINE)
label("ESP32",91,207,18,NAVY,True)
label("只画需要的端子",91,237,10,MUTED)
rect(378,192,135,230,white,LINE)
label("DHT11",397,207,18,NAVY,True)
leftx,rightx=214,378
for yy,lt,rt,col in [
    (276,"3V3","1  VDD",HexColor("#BD4942")),
    (332,"IO4","2  DATA",TEAL),
    (397,"GND","4  GND",HexColor("#4C5964"))
]:
    label(lt,89,yy-10,12,NAVY,True);label(rt,390,yy-10,12,NAVY,True)
    ln(leftx,yy,rightx,yy,col,2.4)
    for xx in [leftx,rightx]:
        c.setFillColor(col);c.circle(xx,H-yy,3,stroke=0,fill=1)
ln(285,276,285,287,HexColor("#BD4942"),2)
rect(277,287,16,29,white,TEAL,r=1)
ln(285,316,285,332,TEAL,2)
label("4.7kΩ",306,292,11,TEAL,True)
label("3  NC：留空",390,361,10,RED,True)
label("电阻一端接 3V3，另一端接 DATA。",70,449,12,TEAL,True)
y=step(1,"接电源和地","DHT11 第 1 脚接 3V3；第 4 脚接 GND。",507)
y=step(2,"接信号线","DHT11 第 2 脚接 ESP32 的 IO4。",y)
y=step(3,"加上拉电阻","4.7kΩ 电阻跨在第 1 脚与第 2 脚所在的两个连接点之间。第 3 脚不接任何线。",y)
p("拍一张能看清两端标识的照片。图为电气连接关系，不是排针或面包板的真实位置图。",y,size=10.5,leading=17,color=MUTED)

# 07
page("通电前后，用万用表查一遍","如果不熟悉表的档位，先对照这块表自己的说明书。")
y=note("先断电，再测电阻或连通","黑表笔插 COM；红表笔插标有 V/Ω 的插孔。这里不要把红表笔插到 A 或 10A 电流插孔，也不要用电流档跨接电源。",151,"stop")
y=step(1,"断电核对电阻","电阻未接入电路时用电阻档测量，确认约为 4.7kΩ。接入电路后测到的数值可能受其他元件影响。",y)
y=step(2,"断电核对连通","用连通档确认每根线的两端确实相连；查看是否把 3V3 和 GND 误插进同一组孔。不把蜂鸣器的一声响单独当成整块板正常。",y)
y=step(3,"只接 USB 电源，测直流电压","切到直流电压档（DC V），黑表笔碰传感器 GND，红表笔碰 VDD。选自动量程或能覆盖 3.3V 的量程，表笔不要同时碰到相邻脚。",y)
y=step(4,"记录读数，再决定继续","目标供电约为 3.3V，记录实际值并核对器件允许范围。若接近 0V、接到了 5V、明显异常或器件发热，立即拔 USB，回到接线检查。",y)
y=check("接线已拍照；供电实测：________ V；电阻：________ kΩ",y)
p("这一轮只由 USB 给开发板供电，不同时接另一组外部电源。不要在带电状态移动传感器、插拔杜邦线或更换电阻。",y,size=11,leading=18,color=RED)

# 08
page("电脑准备：找到项目和串口","烧录就是把程序写进开发板。先确认电脑能找到这块板。")
y=step(1,"拿到已准备好的项目文件夹","使用第 2 页确认的完整项目。打开后应能看到 firmware 文件夹。不要只拿旧版本压缩包或单独一个 bin 文件猜地址烧录。",153)
y=step(2,"在项目文件夹打开终端","Windows 可在文件夹右键打开终端；macOS/Linux 可在终端输入 cd 和项目路径。后面的命令都从这个文件夹运行。",y)
y=code("pio --version\npio device list",y,"逐行复制，每行输完按回车")
y=p("第一行应显示 PlatformIO 版本；第二行列出串口。若提示找不到 pio，先让 Codex 配好环境，回到第 2 页，不继续后面的命令。",y,size=11)
y=step(3,"用插拔前后的差别认端口","拔掉开发板时看一次列表，重新接上后再看。新出现并对应这块板的端口才是要用的端口。",y+18)
y=table(["系统","端口长相举例（不能直接照抄）"],[
    ["Windows","COM5"],
    ["macOS","/dev/cu.usbserial-..."],
    ["Linux","/dev/ttyUSB0 或 /dev/ttyACM0"]
],y,[110,CW-110])
p("<b>我的实际串口：</b>________________________________",y,size=12,leading=20)
p("后文命令里的 YOUR_PORT 必须替换成这行记录的实际串口。",y+34,size=10.5,color=TEAL)

# 09
page("第一次烧录：先用本地采集版","这一版先在串口显示数据，不连接平台，便于判断接线是否正常。")
y=note("继续前确认","第 2 页的版本核对和准备已完成；使用确认后的本地采集版。负责软件准备的人应确认该版没有网络账号配置。不要自行删除已有凭据文件。",151,"wait")
y=step(1,"关闭串口监视器","同一个串口不能同时被监视器和烧录程序占用。接线已核对后，用 USB 数据线连接开发板。",y)
y=code("pio run -d firmware/esp32_dht11 -e esp32dev\npio run -d firmware/esp32_dht11 -e esp32dev -t upload --upload-port YOUR_PORT",y,"每行是一条命令；替换 YOUR_PORT 后逐行执行")
y=p("先把 YOUR_PORT 换成第 8 页的串口。第一条构建程序，下一条写入开发板；等待工具明确显示 SUCCESS 或烧录成功。",y,size=11)
y=step(2,"如果一直卡在 Connecting","先排除端口选错、数据线和串口占用。只有确认板型一致、需要手动下载模式时，按住 BOOT，短按 EN，再按工具提示松开 BOOT。",y+17)
y=step(3,"保留烧录结果","把成功或失败的完整终端输出保存。工具说“烧录成功”后，再去第 10 页看传感器数据；这两件事要分别确认。",y)
p("多次失败时不要换随机参数或擦除整块闪存。保留报错文字、板卡型号和实际端口，按第 19 页定位。",y,size=10.5,leading=17,color=MUTED)

# 10
page("打开串口：看懂开发板的输出","串口窗口像开发板的“说话窗口”。先看文字含义，不急着读 JSON。")
y=code("pio device monitor -d firmware/esp32_dht11 -p YOUR_PORT -b 115200 -f direct -f log2file",153,"这是一条完整命令；替换 YOUR_PORT 后执行")
y=table(["看到什么","表示什么","接下来做什么"],[
    ["firmware=...<br/>gpio=4","程序已启动，并报告版本和引脚","核对与准备卡一致"],
    ["first valid frame primed","第一帧用于准备，还不发布温湿度","继续等待后面的有效帧"],
    ["temperature / humidity","程序产生了温度和湿度记录","保存连续日志，进入基线采集"],
    ["DHT11_READ_FAILED","本次读取失败","保留错误；断电核对接线与器件"],
    ["heartbeat: firmware alive","程序还在运行的串口标记","不能仅凭此认定传感器正常"]
],y,[156,177,CW-333],size=10)
y=note("第一次没有温湿度，不一定是坏了","DHT11 返回的是前一次转换的数据。程序先做一次准备，再发布后续有效读数。准备后仍反复失败才按故障步骤检查，不填“估计室温”。",y)
p("日志保存在 firmware/esp32_dht11/logs 文件夹，启动时也会打印完整路径。结束监视通常按 Ctrl+C；把本次日志复制到实验记录目录，不要只截一行成功画面。",y,size=11,leading=18)

# 11
page("第一次准备板上的“小记事本”","LittleFS 用来保存一批暂时没发出去的数据。全新设备只初始化一次。")
y=note("这一步会替换板上的文件系统","只有明确是新设备、没有要保留的数据，才能执行。用过的设备、情况不明的设备或已有待发数据的设备，先停下核对。",151,"stop")
y=step(1,"确认初始化镜像已经核对","由负责软件准备的人确认 littlefs.bin 和这块板的分区匹配。不能用别人的镜像，也不能仅凭文件名相同判断可用。",y)
y=step(2,"关闭串口窗口，保持 USB 连接","端口仍使用第 8 页记录的那个。",y)
y=code("pio run -d firmware/esp32_dht11 -e esp32dev -t buildfs\npio run -d firmware/esp32_dht11 -e esp32dev -t uploadfs --upload-port YOUR_PORT",y,"每行是一条命令；替换 YOUR_PORT 后逐行执行")
y=step(3,"记录这次初始化","写下日期、板卡编号、镜像指纹和命令结果。以后只是更新程序或更换平台账号，不重复做 uploadfs。",y)
y=note("看到 storage unavailable 怎么办？","这是存储不可用。保存日志，把板卡身份和本次镜像记录交给 Codex 排查；不要反复初始化、格式化或擦除来试运气。",y,"wait")
p("初始化工具报告成功后，还要在联网阶段和缓存实验中验证实际保存与读取。",y,size=10.5,color=MUTED)

# 12
page("接平台之前：先把“房间”开好","平台准备完成后，你在浏览器登录并开始一次实验。")
y=step(1,"请 Codex 完成软件准备","部署独立测试平台，准备测试资料包、学生账号、设备和任务。网页能打开之后，填写下面的交接卡。复杂的部署命令不需要现场操作员边接线边学习。",151)
y=table(["交接项","填写或核对"],[
    ["平台网页地址","http://________________:18081"],
    ["学生账号","____________________________"],
    ["任务名 / 设备标识","____________________________"],
    ["软件准备已完成","确认人：________ 日期：________"]
],y,[165,CW-165])
y=step(2,"登录学生页面","打开准备好的网页，输入自己的测试学生账号和密码，点击“验证学生账号”。密码私下保管，不写进公开实验表。",y)
y=step(3,"选对任务和设备，再开始","选择本次真实硬件的任务和设备，点击“开始所选实验”。请 Codex 核对这次实验的会话编号和资料包，保存交接记录。",y)
y=note("为什么要先开始实验？","平台需要知道“这块板的数据属于哪一次实验”。之后给开发板配置的会话编号，必须来自这次开始操作，不能随手编一个。",y)

# 13
page("让开发板知道把数据发到哪里","先完成第 12 页，再配置联网版程序。")
y=p("请在电脑上打开 firmware/esp32_dht11/include/secrets.h。由 secrets.example.h 复制创建；已有文件先保留核对。下面的示意值都要替换，不能原样烧录。",150,size=11)
y=code('#define XJ_WIFI_SSID "YOUR_WIFI"\n#define XJ_WIFI_PASSWORD "YOUR_WIFI_PASSWORD"\n#define XJ_API_BASE_URL \\\n  "http://SERVER_IP:18081/api/v1/device/ingest"\n#define XJ_DEVICE_ID "YOUR_DEVICE_KEY"\n#define XJ_DEVICE_TOKEN "YOUR_DEVICE_TOKEN"\n#define XJ_EXPERIMENT_SESSION_ID "YOUR_SESSION_ID"\n#define XJ_CA_CERT ""\n#define XJ_ALLOW_INSECURE_HTTP 1',y+18,"只用于本次隔离实验网的 HTTP 配置示意")
y=table(["你要填的东西","从哪里取得"],[
    ["Wi-Fi 名称与密码","实验用的 2.4GHz Wi-Fi"],
    ["SERVER_IP","实际运行平台的电脑局域网 IP；不填 localhost"],
    ["DEVICE_KEY / TOKEN","本次设备标识与它自己的令牌"],
    ["SESSION_ID","第 12 页开始实验后生成的会话编号"]
],y,[180,CW-180],size=10.5)
y=p("<b>填好后：</b>让 Codex 核对，重新执行第 9 页的构建和程序烧录，再打开第 10 页串口。不要重做第 11 页的 uploadfs。",y,size=11,leading=18)
p("这个文件和编译后的联网固件可能含密码；留在私有目录，不发到公开群或仓库。保持测试标记开启。",y+48,size=10.5,leading=17,color=MUTED)

# 14
page("正常采集：先把一轮数据留完整","目标是同时看到板上采集和平台收到，先不做故障实验。")
y=step(1,"打开串口和学生页面","程序开始后先经过准备帧，再看温湿度。看到 accepted request=...，说明某批请求得到了程序认可的回执。",151)
y=step(2,"核对网页上的新数据","刷新查看本次设备和实验的数据，请 Codex 对照同一个请求编号确认入库。仅看到“在线”不能证明温湿度已入库。",y)
y=step(3,"收集至少 30 次完整有效采样","一次完整有效采样要同时有温度和湿度。配置约每 3 秒请求一次，通常要约 2 分钟起；网络暂停或读取失败时应延长，完整保留失败记录。",y)
y=step(4,"按准备好的表再做两轮","先导阶段做三次独立启动，各留自己的日志。之后 Codex 用这些数据设置读数时限，再交付新版资料包；新的验收数据另采，不能拿同一批数据自证通过。",y)
y=note("看到“未知”，先检查，不急着判硬件坏","当前资料包还没有完整读数时限，所以有数字也可能显示未知。另外，设备时钟尚未同步也会影响恢复判断。把页面与原始日志保留下来。",y)
p("达到这一页的目标后，才进入断线和断网实验。基线本身反复失败时，先按第 19 页定位。",y,size=11,leading=18)

# 15
page("断线实验：只动这一根信号线","先正常，再断开，最后接回。每次改线之前都拔掉 USB。")
rect(M,151,CW,140,PALE)
label("只断开绿色信号连接",M+17,166,13,TEAL,True)
label("ESP32 IO4",M+20,218,12,NAVY,True)
label("DATA 节点",M+365,218,12,NAVY,True)
ln(M+115,230,M+211,230,TEAL,3)
ln(M+271,230,M+353,230,TEAL,3)
label("断开处",M+218,249,10,RED,True)
ln(M+220,216,M+249,241,RED,2);ln(M+220,241,M+249,216,RED,2)
p("DATA 侧的 4.7kΩ 上拉仍留着；3V3、GND 及其他接线保持不变。",270,x=M+15,w=CW-30,size=10.5,leading=16)
y=step(1,"保存正常基线","先确认第 14 页通过，保存接线照片、最新采样和平台结果。",313)
y=step(2,"拔 USB，再拔信号线的一端","只断开 IO4 通往 DATA 节点的那根杜邦线，把松开的线头放好，避免碰到其他针脚。拍下断开位置。",y)
y=step(3,"重新插 USB，观察失败记录","程序仍可能有心跳，但传感器读取会失败。记录完整输出，不修改程序来制造错误。",y)
y=step(4,"让 Codex 做本轮异常检查","使用约定的 90 秒回看窗口核对累计 5 次失败是否命中规则。你看到的“断线”来自现场操作；平台仅凭失败日志不应武断说器件坏了。",y)
p("如果拔掉的是电源线、地线，或同时改了两根线，这轮不能算单因素断线实验。恢复原样后另开一轮记录。",y,size=10.5,leading=17,color=RED)

# 16
page("接回信号线：用新数据确认恢复","接好了只是开始，接下来还要看新的采样和新的平台判断。")
y=step(1,"先拔 USB，再恢复原接线","把信号线接回第 6 页的位置，检查电源与地没有松动，拍照后再接 USB。",153)
y=step(2,"等待准备帧和新的温湿度","第一次有效帧仍只用于准备。后面出现有效温湿度，并且平台收到新的记录，才说明采集和上传恢复了。",y)
y=step(3,"用新的诊断复查","请 Codex 基于最新诊断和新数据发起 90 秒窗口的恢复检查。当前网页按钮默认回看 1 小时，不要把反复点击网页当作本轮固定窗口检查。",y)
y=step(4,"旧错误还在窗口里时继续采集","最后一次失败后至少让完整的 90 秒窗口过去，再由 Codex 核对实际输入和新数据。不能删除旧错误来让页面变绿。",y)
y=table(["分别记录","你要看到什么"],[
    ["读取恢复","串口有新的有效温度、湿度"],
    ["上传恢复","平台有对应的新记录"],
    ["系统确认恢复","新包时限、设备时间和其他判断条件均满足"]
],y,[125,CW-125],size=10.5)
p("三个结果不能混为一个。仍为“未知”就记录未知，并说明缺哪项。完整“正常—断线—恢复”做三轮，每轮单独保存材料。",y,size=11,leading=18)

# 17
page("断网实验：试试数据能否等一等","先保证正常上传；本轮只控制专用实验 Wi-Fi，平台服务保持运行。")
y=note("板上只保存一批，满了会暂停采样","这不是能长时间连续记录的“大仓库”。暂停期间没有新读数是当前设计行为，需要如实记录，不补造数据。",151)
y=step(1,"记录最后一次成功，再让开发板失联","只关闭专用实验 Wi-Fi 或按预定方法断开板卡连接。不要修改日常代理、关闭平台服务或影响别人的网络。",y)
y=step(2,"保留失联前后的完整日志","可能出现一批新数据，然后批次不再增长，程序仍有运行标记。请 Codex 核对待发批次，不把“没报错”单独当作已经保存。",y)
y=step(3,"恢复原来的实验 Wi-Fi","看开发板是否自行重连，原批次能否继续发送。若没有自动重连，记录失败；按复位才成功要算另一种情况。",y)
y=step(4,"核对同一批只入库一次","由 Codex 对照原请求编号和服务端记录，确认补传身份没有换、没有重复计数；继续观察重新准备后产生的新采样。",y)
y=note("如果显示 retry budget exhausted","表示这批的发送次数用尽，数据还被保留。停止本轮并保存日志；不要重刷文件系统清数据，也不要以重启一定能解决。Wi-Fi在线但服务器不可达会消耗次数。",y,"wait")

# 18
page("重启保留：另做一轮，不混在断网里","这一页先由 Codex 确认可执行的取证流程，再操作硬件。")
y=note("先证明有一批数据已经保存","程序没有专用的“导出缓存”按钮。要核对板上文件时，由熟悉工具的人只读备份闪存并解包；现场操作员不要自行擦除或写回闪存。",151,"wait")
y=step(1,"按第 17 页生成待发送批次","保持网络断开，记录批次与设备状态。由 Codex 核对所需证据已准备好。",y)
y=step(2,"记录时刻，拔 USB 断电","传感器和板卡一起断电。保持原接线，不同时换线或更换设备。",y)
y=step(3,"重新接 USB，仍先保持断网","保存启动日志。预期能找到 retained request=... 之类的保留请求信息，由 Codex 与原批次核对。",y)
y=step(4,"恢复网络，检查原请求和新采样","原批次仍应属于原实验，不能换个编号当新数据；之后再观察重新准备与有效读数。",y)
y=p("<b>本页的结论：</b>只说明本轮所记录的重启情形。不能据此声称任意时刻掉电都不会丢数据，也不能把读闪存引起的重启当作“没有重启的自动重连”。",y,size=11,leading=18)
p("今天不做：短路、过压、故意损坏传感器、反复格式化、随机切断闪存写入。这些不是完成第一轮实验所需的操作。",y+70,size=11,leading=18,color=RED)

# 19
page("卡住时，按现象找下一步","一次只处理一个问题。先保存现场，再动手修改。","随手查")
y=table(["你遇到的现象","先做这件事"],[
    ["电脑找不到串口","换确认支持数据的USB线；插拔对照端口；核对实际USB-UART驱动。"],
    ["烧录提示端口被占用","关闭串口监视器和其他串口软件，再试同一端口。"],
    ["串口乱码","确认波特率115200，按第10页重新打开监视器。"],
    ["一直读取失败","先拔USB，再核对四针方向、GPIO4、3V3、GND和4.7kΩ上拉。"],
    ["串口有值，网页没数据","核对平台IP、实验Wi-Fi、设备身份和当前会话；让Codex查看回执。"],
    ["401 / 403","账号或设备凭据/授权不匹配；核对，不切换到演示接口绕过。"],
    ["409","请求、会话或版本冲突；保留原请求，让Codex读当前状态。"],
    ["有值，仍显示未知","核对读数时限、设备时间和旧错误窗口，不直接判硬件损坏。"],
    ["storage unavailable","保存日志和初始化记录，停止重刷或格式化，交给Codex排查。"],
    ["retry budget exhausted","本批发送次数耗尽，先保留数据，不靠重启或清队列解决。"]
],152,[154,CW-154],size=10.3,pad=8)
y=note("这些情况先拔 USB","明显发热、异味、冒烟、供电接错、裸露线头碰到其他针脚，或无法确定引脚方向。先断电再核对接线。",y,"stop")
p("求助时提供：做到第几页、板卡/传感器标识、接线照片、报错全文、固件版本。勿发送密码或设备令牌。",y,size=10.5,leading=17)

# 20
page("打印填写：30 次采样记录","每一行要有温度和湿度才算一次完整有效采样。原始日志同时保留。","可打印记录表")
y=p("运行编号：________________  日期：________________<br/>操作者：__________________  日志文件：____________",145,size=11,leading=22)
rows=[]
for i in range(1,16):
    rows.append([str(i),"","","",str(i+15),"","",""])
y=table(["序号","温度°C","湿度%RH","成功/失败","序号","温度°C","湿度%RH","成功/失败"],
        rows,y+20,[31,64,66,93,31,64,66,CW-415],size=8.8,pad=6)
p("开始时间：____________  结束时间：____________<br/>期间读取失败次数：______  断网或暂停：________________<br/>本表完整有效次数：______  未成功原因：________________",y+4,size=11,leading=25)
p("如果某次失败，写“失败”并保留日志；继续采样到有效次数满足本轮目标，另附续页。不要把失败行改成估计值。",y+93,size=10.5,leading=17,color=MUTED)

# 21
page("打印填写：这一轮到底完成了什么？","未做的项目填“未执行”；做了但失败的项目填“失败”。","可打印记录表")
y=p("运行编号：________________  操作者：________________<br/>板卡/传感器编号：___________________________________<br/>固件/资料包版本：___________________________________<br/>实际串口 / 平台地址：_______________________________",145,size=11,leading=25)
y=table(["检查项","通过 / 失败 / 未执行","日志或照片位置"],[
    ["器材和脚号核对","",""],
    ["接线、阻值和供电核对","",""],
    ["本地采样及首次准备","",""],
    ["平台收到真实数据","",""],
    ["断开DATA后的异常","",""],
    ["恢复后的新采样/入库","",""],
    ["系统是否确认恢复","",""],
    ["断网后原批次补传","",""],
    ["重启后原批次保留","",""]
],y+16,[169,159,CW-328],size=10,pad=9)
p("本轮只改了什么：___________________________________<br/>还有什么没解决：___________________________________<br/>下次先做什么：_____________________________________",y+4,size=11,leading=25)
p("签名和时间在实际完成后填写。这里记录内部实验，不替代课程成绩、精度检测或教师审核。",y+94,size=10.5,leading=17,color=MUTED)

# 22
page("记住这些词，就够你完成第一轮","需要复杂软件操作时，把明确任务交给 Codex，不必先记住全部专业名词。","词语与依据")
y=table(["词语","用最简单的话说"],[
    ["固件 / 烧录","开发板运行的程序 / 把程序写进开发板。"],
    ["串口 / 波特率","电脑和板子的文字通道 / 两边约定的通信速度，本实验115200。"],
    ["GPIO4 / 上拉电阻","本次用的信号引脚 / 把信号线通过电阻连接到3.3V。"],
    ["LittleFS / 缓存","板上的小文件系统 / 暂时没发出去的一批记录。"],
    ["会话 / 请求编号","这是哪一次实验 / 这是哪一批数据。"],
    ["日志 / 哈希","过程记录 / 文件内容指纹。原始日志和指纹一起保留便于复查。"],
    ["准备帧（priming）","先读一次作准备，这次不当作正式温湿度。"],
    ["未知（unknown）","证据或判断条件不足，暂时不能下结论。"]
],151,[150,CW-150],size=10.4,pad=7)
y=p("技术依据和使用范围",y+4,size=14,leading=21,bold=True)
y=p('四针DHT11方向、脚号与电气资料：<link href="https://www.aosong.com/userfiles/files/media/DHT11-V1_3%E8%AF%B4%E6%98%8E%E4%B9%A6%EF%BC%88%E8%AF%A6%E7%BB%86%E7%89%88%EF%BC%89.pdf" color="#007F83">奥松 DHT11 V1.3_20170331 手册，PDF第2、4页</link>。<br/>开发板标识与引脚：<link href="https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html" color="#007F83">Espressif ESP32-DevKitC V4 官方指南</link>。<br/>构建与文件系统工具：<link href="https://docs.platformio.org/en/latest/platforms/espressif32.html" color="#007F83">PlatformIO Espressif32 文档</link>。',y+9,size=10,leading=16)
y=p("项目依据：docs/experiments/dht11-hardware-execution-plan.md，以及当前固件和资料包源码。本册是该方案的现场操作读本；初始化、发布和故障恢复的技术细节仍按已审阅方案执行。",y+12,size=10,leading=16)
p("本册中的图均为说明示意，不是已完成实验的照片；空表、示意配置和文字输出不是实测结果。软件修复证据见项目修复报告；各阶段实物结果在实际执行后另行记录。",y+12,size=10,leading=16,color=MUTED)

assert page_no==TOTAL,(page_no,TOTAL)
# Catch missing glyphs in the two embedded Chinese faces (HTML markup is ignored).
import re
plain=re.sub("<[^>]+>","", "\n".join(TEXTS))
missing=sorted({ch for ch in plain if ord(ch)>127 and ord(ch) not in pdfmetrics.getFont("CN").face.charToGlyph})
if missing:raise RuntimeError("missing CJK glyphs: "+repr(missing))
c.save()
print(OUT)
print(f"pages={page_no}")
