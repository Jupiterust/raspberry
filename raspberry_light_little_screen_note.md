#####
MIPI : mobile Industry processor interface
DBI : display bus interface
DCS L Display Comment Set

.dtbo: (Device Tree Overlay) overlay:补丁: 补丁设备树

mipi-dbi-spi.dtbo          →    描述硬件：SPI总线上有个屏
                                 compatible = "panel-mipi-dbi-spi"
                                          ↓
                                    内核记录这个设备

panel-mipi-dbi.ko           →    驱动代码，声明自己能处理
                                 compatible = "panel-mipi-dbi-spi"
                                          ↓
                                    内核记录这个驱动

内核发现两边 compatible 对上了  →  调用 probe()，屏幕开始工作

内核源码 panel-mipi-dbi.c  →  编译  →  panel-mipi-dbi.ko
设备树源码 mipi-dbi-spi.dts →  dtc   →  mipi-dbi-spi.dtbo

#####
# 树莓派点亮 SPI 屏完整学习笔记

> 本文档复盘在 **树莓派 5 + Ubuntu 22.04(内核 6.8)** 上点亮一块 **2.0" ST7789V2 SPI 屏**的全过程。
> 重点不是"记住命令",而是理解**每一步在干什么、为什么、换屏换系统时怎么迁移**。

---

## 〇、先建立一个总览:点亮任意屏的五步方法论

无论什么屏、什么 Linux 发行版,点亮的骨架都是这五步。**做法会变,但每步要回答的问题不变。**

| 步骤 | 在干什么 | 换屏/换系统时问自己 |
|---|---|---|
| ① 摸清两端能力 | 确认屏的接口和系统的驱动支持 | 屏是什么接口/IC/分辨率?系统内核有没有对应驱动? |
| ② 准备两块描述 | 初始化序列 + 接线规格 | 这块屏怎么唤醒?它接在哪、长什么样? |
| ③ 告诉系统去加载 | 配置启动项 + 文件放对位置 | 这个系统用什么配置机制?文件放哪、叫什么? |
| ④ 分层验证 | 软件链路逐层确认 → 锁定硬件 | 软件全通了吗?通了就查硬件接线 |
| ⑤ 配成实际用途 | 显示器 / 终端 / 信息面板 | 这块屏在项目里扮演什么角色? |

**核心心法:遇到新屏/新系统,先用这五步问对问题,再去查那个具体系统怎么做。**

---

## 0.5 通过例子学会这五步

以本文例子 `树莓派 5 + Ubuntu 22.04 + 2.0" ST7789V2 SPI 屏` 为主线,把五步映射到实际操作:
(IC : Integraded Circuit)
- **① 摸清两端能力**:屏是 SPI 接口,IC 是 ST7789V2,分辨率 240×320;系统要有 `mipi-dbi-spi.dtbo` overlay 和 `panel-mipi-dbi` 驱动,内核要能加载这个模块。
- **② 准备两块描述**:把屏的初始化序列写成 `panel.txt`,用 `mipi-dbi-cmd` 编译成 `/lib/firmware/panel-mipi-dbi-spi.bin`;把屏的接线和尺寸写进 `config.txt` 的 `dtoverlay=mipi-dbi-spi` 参数里。
- **③ 告诉系统去加载**:修改 `/boot/firmware/config.txt`,启用 SPI,加载 overlay,指定 `compatible=panel-mipi-dbi-spi`,并确保固件文件放在 `/lib/firmware`。
- **④ 分层验证**:先看 overlay/驱动是否存在,再查 `dmesg` 里是否有 `panel-mipi-dbi` probe 成功,然后确认 `/dev/fb0` 出现并且 `cat /sys/class/graphics/fb0/virtual_size` 显示 240,320,最后用 `cat /dev/urandom | sudo tee /dev/fb0` 验证数据通路。
#
第一层：overlay 和驱动文件存在？
ls /boot/overlays/mipi-dbi-spi.dtbo
modinfo panel-mipi-dbi↓

第二层：probe 成功了吗？
dmesg | grep panel-mipi-dbi↓

第三层：framebuffer 设备出现了吗？
ls /dev/fb0
cat /sys/class/graphics/fb0/virtual_size  # 应该显示 240,320↓

第四层：数据通路通吗？
cat /dev/urandom | sudo tee /dev/fb0     # 屏幕应该出现雪花
#
- **⑤ 配成实际用途**:决定这块屏是做小桌面显示,还是只跑终端/信息面板,然后配置系统启动目标、自动登录或者展示程序。

同样的五步,换屏/换系统的本质不变:

- 换 SPI 屏:第 ② 步的 `panel.bin` 和 `width/height/GPIO` 改成新屏参数,其他步骤保持不变。
- 换 DSI 屏:仍然先确认内核支持,但第 ② 步变成写专属 panel 驱动 `.c` 和屏幕规格 DTS,第 ③ 步改成对应的设备树机制。

---

## 一、MIPI / SPI / I2C:屏幕通信方式的本质区别

理解这个,才知道为什么 SPI 屏和 DSI 屏的点亮方式差别那么大。

### 最关键的一个差别:屏幕自不自带显存(GRAM)

- **MIPI DSI / RGB 并口**:屏幕通常**不自带显存**。主机必须按时序**不停地**把每一帧像素流刷过去,一停就黑。所以需要复杂的时钟/前后肩时序参数。
- **SPI / I2C 屏**:屏幕驱动 IC **自带 GRAM**。主机把一帧画进去就可以撒手不管,屏幕自己保持显示。所以**不需要时序刷新参数**——这就是为什么 SPI 屏的设备树比 DSI 简单得多。

### 三种接口横向对比

| | MIPI DSI | SPI | I2C |
|---|---|---|---|
| 速度 | 很快(Gbps) | 中等(几十 MHz) | 慢(几百 kHz~几 MHz) |
| 线数 | 差分多对+时钟 | 4~6 根 | 2 根 |
| 屏自带显存 | 一般不带 | **带** | **带** |
| 典型尺寸 | 5"+ 高清屏 | 1.3"~3.5" 小彩屏 | 0.96" OLED |
| 典型 IC | ST7701、ILI9881 | ST7789、ILI9341 | SSD1306 |

### SPI 屏的两条驱动路线

这是容易混的地方,SPI 屏有两种完全不同的接法:

- **路线 A:当成"真正的显示设备"走 DRM**(本文走的就是这条)
  用内核的 `panel-mipi-dbi` / tinydrm 子系统,把 SPI 屏伪装成标准显示设备。能显示桌面/终端。
- **路线 B:当成"普通外设",用户态直接驱动**
  不碰 DRM,在自己的程序里用 SPI 库一条条发命令和像素(类似你在 STM32 上裸机驱动 OLED)。只能显示自己程序画的东西。

---

## 二、DRM/KMS 显示分层:谁是现成的,你要补什么

这是理解整个驱动的地基。一块屏从"应用想画东西"到"屏幕亮起",中间有好几层:

```
应用 / 桌面
    ↓
DRM / KMS 框架          ← 内核现成,不用动
    ↓
SPI 控制器驱动           ← 内核现成,不用动(DSI 屏这里是 VC4 DSI Host)
    ↓
=== D-PHY / SPI 物理线(硬件)===
    ↓
panel 驱动 (panel-mipi-dbi)  ← SPI 屏有通用驱动兜底;DSI 屏要自己写
    ↓
屏幕驱动 IC (ST7789)
    ↓
液晶面板亮起
```

**你要补的只有两块**(对应方法论第②步):

1. **初始化序列**(怎么唤醒屏)→ SPI 屏是 `panel.bin`;DSI 屏是 panel 驱动 `.c` 文件
2. **接线和规格描述**(屏接在哪、长什么样)→ 设备树 overlay 里的参数

SPI 屏的最大好处:**有通用驱动 `panel-mipi-dbi`,不用自己写 .c**,只要喂一个初始化命令的二进制文件就行。DSI 屏没这种通用驱动,每块屏都要写专属 panel 驱动。

---

## 三、第①步:体检三连——确认系统支持

点屏前先确认系统具不具备条件,这是方法论第①步的具体落地。

```bash
# 1. 查 mipi-dbi-spi overlay 在不在
ls /boot/firmware/overlays/ | grep mipi

# 2. 查 panel-mipi-dbi 驱动模块在不在
find /lib/modules/$(uname -r) -name "*mipi-dbi*"
modinfo panel-mipi-dbi 2>/dev/null && echo "驱动在" || echo "驱动缺失"

# 3. 看内核版本
uname -r
```

### 知识点:这三条在查什么

- **overlay 文件**:设备树片段的编译产物(`.dtbo`)。`mipi-dbi-spi.dtbo` 是描述"一块 SPI 屏怎么接"的模板。
- **驱动模块**:`panel-mipi-dbi.ko` 是真正干活的代码。`modinfo` 能看它的别名(`alias`),其中 `panel-mipi-dbi-spi` 就是后面 config 里要写的 compatible。
- **内核版本**:决定新驱动支不支持。本例是 `6.8.0-1056-raspi`,够新,直接走主路。

### 迁移要点

- **换发行版**:Raspberry Pi OS 默认这些都全;Ubuntu 可能 overlay 旧或缺;Yocto 要自己在配方里加。但"确认 overlay + 驱动 + 内核版本"这三个问题不变。
- **结果分叉**:都齐 → 走主路;缺 overlay → 单独拷 `.dtbo`;缺驱动 → 升级系统或换用户态路线。

---

## 四、第②步:准备 panel.bin(初始化序列)

### 知识点:panel.bin 是什么

它是把"屏幕初始化命令序列"编译成的二进制文件。这些命令就是屏厂 datasheet 里规定的"怎么唤醒这块屏":设色彩曲线、电源、退睡眠、开显示。通用驱动 `panel-mipi-dbi` 启动时读这个文件,通过 SPI 用 **DCS 命令**发给屏。

### 操作

```bash
# 拿编译脚本
git clone https://github.com/notro/panel-mipi-dbi.git
cd panel-mipi-dbi

# 写初始化序列(本例 240×320 ST7789V2)
cat > panel.txt << 'EOF'
command 0x11        # Sleep Out 退出睡眠
delay 120
command 0x36 0x00   # MADCTL 显示方向(关键!旋转屏幕改这里)
command 0x3A 0x05   # 像素格式 RGB565
command 0x21        # 反色(ST7789 多数需要;颜色反了就删这行)
command 0x13        # Normal Display On
command 0x29        # Display On 开显示
delay 100
EOF

# 编译成二进制
python3 mipi-dbi-cmd panel.bin panel.txt

# 拷到固件目录,文件名必须是驱动找的那个!
sudo cp panel.bin /lib/firmware/panel-mipi-dbi-spi.bin
```

### 常用命令字含义(DCS 标准命令)

| 命令 | 含义 |
|---|---|
| `0x11` | Sleep Out,退出睡眠 |
| `0x29` | Display On,开显示 |
| `0x28` | Display Off,关显示 |
| `0x36` | MADCTL,内存访问控制(管旋转/翻转/RGB顺序) |
| `0x3A` | 像素格式(`0x05`=RGB565,`0x06`=RGB666) |
| `0x21` | 反色开 |
| `0x20` | 反色关 |

### ⚠️ 坑 1:文件名必须对

驱动默认找的文件名是 `panel-mipi-dbi-spi.bin`,不是 `panel.bin`。
本例就因为先拷成了 `panel.bin`,导致开机报错:
```
Direct firmware load for panel-mipi-dbi-spi.bin failed with error -2
```
`error=-2` 就是"文件找不到"。改名拷一份即可解决。

### 迁移要点

- **换屏**:初始化序列从新屏的 datasheet 或厂家 init code 抄。这是每块屏唯一真正不同的核心内容。
- 不确定 `0x36` 填什么、要不要 `0x21`,先去 notro 的 wiki 找同款屏配置最快。

---

## 五、第③步:写 config.txt(告诉系统去加载)

### 操作

```bash
sudo nano /boot/firmware/config.txt
```

在末尾加(注意别加进 `[pi4]`/`[cm4]` 这种分段里):

```
dtparam=spi=on                                      # 打开 SPI 总线
dtoverlay=mipi-dbi-spi,spi0-0,speed=40000000        # 加载 overlay,SPI0 CE0,40MHz
dtparam=compatible=panel-mipi-dbi-spi               # 指定用哪个驱动(对应 modinfo 的 alias)
dtparam=width=240,height=320                        # 分辨率
dtparam=reset-gpio=27,dc-gpio=25,backlight-gpio=24  # 三个控制脚的 GPIO 号
```

### 知识点:每个参数的含义

- `dtparam=spi=on`:启用硬件 SPI 外设。
- `dtoverlay=mipi-dbi-spi`:加载那块描述 SPI 屏的设备树模板。`spi0-0` = SPI0 的 CE0 片选;`speed` = SPI 时钟频率。
- `compatible=panel-mipi-dbi-spi`:告诉系统"这块屏用 panel-mipi-dbi 驱动",和 `modinfo` 看到的 alias 对应。
- `width/height`:分辨率,要和屏实际一致。
- `reset-gpio/dc-gpio/backlight-gpio`:复位、数据命令、背光三个脚用哪个 GPIO(BCM 编号)。

### ⚠️ 坑 2:BCM 编号 vs 物理引脚号

config 里写的 GPIO 号是 **BCM 逻辑编号**(GPIO 25),不是树莓派排针的**物理位置**(Pin 22)。接线看物理位置,写配置用 BCM 号,两者千万别混。

### 迁移要点

- **换发行版**:config.txt 这套是树莓派 bootloader 的机制,Ubuntu 和 Raspberry Pi OS 都在 `/boot/firmware/config.txt`,通用。别的板子(非树莓派)可能直接改设备树源文件或 U-Boot 环境变量,但"指定 compatible + 接线参数 + 分辨率"的本质不变。

---

## 六、第④步:分层验证(核心心法)

这是整套方法里最该带走的思维方式。**先确认软件链路从上到下都通,一旦软件全绿,问题必然在硬件**,这时再逐根查线。

### 验证命令

```bash
# 看有没有多出 framebuffer 设备
ls /dev/fb*

# 确认 fb 的身份和分辨率
cat /sys/class/graphics/fb0/name           # 应显示 panel-mipi-dbi
cat /sys/class/graphics/fb0/virtual_size   # 应显示 240,320

# 看驱动加载日志
sudo dmesg | grep -iE "mipi|panel|st7789|drm"

# 打雪花测试出图(数据写进 framebuffer)
cat /dev/urandom | sudo tee /dev/fb0 > /dev/null
```

### 知识点:分层验证的逻辑链

逐层往下问,每层确认了再看下一层:

1. **驱动 probe 成功了吗?** → dmesg 看到 `Initialized panel-mipi-dbi` 和 `fb0: ... frame buffer device`,无 `failed`。✓
2. **framebuffer 设备出来了吗?** → `ls /dev/fb*` 有 fb0。✓
3. **是我的屏不是 HDMI 吗?** → `name` = panel-mipi-dbi,`virtual_size` = 240,320。✓
4. **数据能写进 framebuffer 吗?** → `cat /dev/urandom > /dev/fb0` 报 `No space left on device`,这其实是**好事**——说明数据灌满了 fb0(fb0 大小固定,灌满就停),证明软件通路全通。✓

**软件四层全绿,但屏没反应 → 问题 100% 在硬件。** 这时候才去查接线。

### 知识点:`No space left on device` 不是错误

`cat /dev/urandom > /dev/fb0` 这条会一直往 fb0 灌数据,但 fb0 是固定大小(240×320×2 字节),灌满就停并报这个。**它恰恰证明数据成功写进了 framebuffer。** 别被"error"字样吓到。

### ⚠️ 坑 3:DC 接错(本例的真凶)

软件全部正常,但屏黑/无反应,最后发现是 **DC 这根线接错了**——把 DC 接到了错误的脚。
DC(Data/Command)的作用是告诉屏"我现在发的是命令还是像素数据"。DC 错了,屏分不清命令和数据,初始化全乱,所以一直黑屏。
**DC 接错是 SPI 屏黑屏的头号嫌疑。** DC 一接对,屏立刻显示。

### 知识点:背光是独立的一条线

本例屏的背光只要 VCC 通电就常亮,**BLK 脚不控制背光**(不同模组不一样)。排查时发现"VCC+GND 一接背光就亮",说明背光和显示是两套独立的东西:
- 背光不亮 → 你什么都看不见,即使屏在正常刷图
- 背光亮但屏黑 → 是显示通路(SPI/DC/初始化)的问题

排查黑屏要分清是"背光问题"还是"显示问题"。

### 迁移要点

分层验证法点任何外设都管用:**先确认软件栈每一层都正常,锁定问题在硬件后,再逐个排查物理连接。** 这能把"哪里都可能错"的茫然,缩小成"就是某根线"的精确定位。

---

## 七、屏幕旋转:0x36 (MADCTL) 详解

### 知识点

屏幕方向由 panel.bin 里的 `0x36`(MADCTL,Memory Access Control)命令控制。改这个字节就能旋转/翻转。

| 0x36 值 | 效果 |
|---|---|
| `0x00` | 默认(竖屏) |
| `0xC0` | 旋转 180°(仍竖屏,上下翻) |
| `0x60` | 旋转 90°(横屏) |
| `0xA0` | 旋转 270°(横屏,另一方向) |

### 关键技巧:再转 180° = 当前值 XOR 0xC0

`0xC0` 那两个 bit 控制 X/Y 翻转,异或它们就等于转 180°:
- `0x60` XOR `0xC0` = `0xA0`
- `0x00` XOR `0xC0` = `0xC0`

### ⚠️ 注意:横屏要改分辨率

转 90°/270°(横屏)后,宽高对调,config.txt 里的 `width/height` 也要从 `240,320` 改成 `320,240`,否则显示不全或错位。只转 180° 不用改。

### 改完的操作流程

```bash
nano panel.txt                                       # 改 0x36 的值
python3 mipi-dbi-cmd panel.bin panel.txt             # 重新编译
sudo cp panel.bin /lib/firmware/panel-mipi-dbi-spi.bin  # 覆盖
sudo reboot                                          # 重启生效
```

---

## 八、引脚冲突的处理:硬件 SPI vs 软件 GPIO

本例遇到:树莓派用 GPIO 11/10 做 STM32 的 SWD 烧录,而 SPI 屏也要 GPIO 11/10。

### 知识点:为什么让 SWD 让位给屏

- **屏的 SPI(SCLK/MOSI)是硬件外设固定引脚**,GPIO 11/10 挪不了。
- **SWD 烧录是软件模拟(OpenOCD bitbang)**,引脚是配置里自己指定的,随便挪。

**原则:能动的让位给不能动的。** 把 SWD 引脚从 GPIO 11/10 挪到空闲的 GPIO 6/5。

### 操作(改 OpenOCD 配置)

`linuxgpiod` 驱动的写法:
```
adapter gpio swclk -chip 4 6    # 原来是 11,改成 6
adapter gpio swdio -chip 4 5    # 原来是 10,改成 5
```

### 迁移要点

排引脚时先分清:哪些是**硬件外设固定脚**(SPI/I2C/UART 的特定引脚,不能动),哪些是**通用 GPIO 软件用途**(可随意分配)。冲突时让软件用途让位。

---

## 九、第⑤步:配成实际用途——XFCE 桌面 + 自动登录

点亮后让屏当系统显示器,跑 XFCE 桌面。

### 知识点:启动目标(systemd target)

Linux 用 systemd target 控制开机进什么状态:
- `graphical.target` → 启动图形界面(桌面)
- `multi-user.target` → 纯文字终端,不启动图形

切换:
```bash
sudo systemctl set-default graphical.target   # 进桌面
sudo systemctl set-default multi-user.target  # 进终端
systemctl get-default                         # 查当前
```

### 知识点:LightDM 自动登录

小屏太小看不到密码框,所以配置自动登录跳过登录界面。

环境:登录管理器 = **LightDM**,桌面 = **XFCE**。

```bash
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-autologin.conf > /dev/null << 'EOF'
[Seat:*]
autologin-user=jupiter
autologin-user-timeout=0
autologin-session=xfce
EOF
```

- `autologin-session=xfce` 要和 `ls /usr/share/xsessions/` 里的文件名对应(去掉 `.desktop`)。

### ⚠️ 坑 4:黑屏 + 光标 ≠ 桌面崩溃

进桌面后小屏只有黑底 + 鼠标光标,看着像崩了。但 `ps aux | grep xfce` 显示 `xfce4-session`、`xfce4-panel`、`xfdesktop` 全在跑。
真相:**桌面是活的,只是壁纸文件丢失导致背景黑 + 面板被 320×240 挤到看不见。**
验证桌面是否活着:`DISPLAY=:0 xmessage "hello" &`,小屏能弹窗就说明桌面正常。

### ⚠️ 坑 5:从 SSH 操作 :0 需要授权

从 SSH 远程操作图形界面(`DISPLAY=:0`)会遇到 `Invalid MIT-MAGIC-COOKIE-1 key`。需要指定授权文件:
```bash
export DISPLAY=:0
export XAUTHORITY=/home/jupiter/.Xauthority
```

### ⚠️ 坑 6:注销 ≠ 重新登录

LightDM 的自动登录默认**只在开机第一次触发**。注销(logout)后不会自动重登,会停在登录界面——而小屏看不到密码框,就卡死了。
**教训:不要用"注销"来修桌面卡死。** 用 `sudo systemctl restart lightdm` 重走开机登录流程才会触发自动登录。

---

## 十、桌面美化:xfconf-query

XFCE 的所有设置都能用 `xfconf-query` 命令行改,适合从 SSH 远程调小屏。

```bash
# 设壁纸(遍历所有 workspace/monitor 条目)
for p in $(DISPLAY=:0 xfconf-query -c xfce4-desktop -p /backdrop -l | grep last-image); do
  DISPLAY=:0 xfconf-query -c xfce4-desktop -p "$p" -s /usr/share/backgrounds/xfce/xfce-blue.jpg
done

# 面板调小(320×240 上默认 48px 太占地方)
DISPLAY=:0 xfconf-query -c xfce4-panel -p /panels/panel-1/size -s 20
DISPLAY=:0 xfconf-query -c xfce4-panel -p /panels/panel-1/icon-size -s 16

# 底部 dock 自动隐藏
DISPLAY=:0 xfconf-query -c xfce4-panel -p /panels/panel-2/autohide-behavior -s 1

# 字体调小
DISPLAY=:0 xfconf-query -c xsettings -p /Gtk/FontName -s "Sans 9"

# 重载面板生效
DISPLAY=:0 xfce4-panel -r
```

### 知识点:xfconf-query 用法

- `-c <channel>`:配置通道(xfce4-panel、xfce4-desktop、xsettings 等)
- `-p <property>`:属性路径
- `-l`:列出所有属性
- `-s <value>`:设置值

---

## 十一、写脚本:display-mode 模式切换

把"切换启动目标"封装成一个友好的命令。

### 知识点:脚本放 /usr/local/bin 全局可用

放在 `/usr/local/bin/` 里的可执行脚本,任何目录下直接敲名字就能运行。

```bash
sudo tee /usr/local/bin/display-mode > /dev/null << 'EOF'
#!/bin/bash
case "$1" in
  desktop|gui|d)
    sudo systemctl set-default graphical.target
    echo "已设置桌面模式,重启生效:sudo reboot" ;;
  console|terminal|tty|c)
    sudo systemctl set-default multi-user.target
    echo "已设置终端模式,重启生效:sudo reboot" ;;
  status|s)
    systemctl get-default ;;
  *)
    echo "用法: display-mode {desktop|console|status}" ;;
esac
EOF
sudo chmod +x /usr/local/bin/display-mode
```

### 知识点:`chmod +x` 给执行权限

脚本写完必须 `chmod +x` 才能直接运行,否则提示权限不够。

---

## 十二、桌面卡死急救:fix-desktop

### ⚠️ 经验:小屏 + SSH 远程环境,温柔修复反而出问题

试过的几种"温柔"修法都有副作用:
- 单独重起 panel → 进程挂在 SSH 终端下,断开就死,还刷屏报错
- 注销会话 → 卡在登录界面(坑 6)
- 重起桌面组件 → 壁纸丢失黑屏

**最可靠的是直接重启整个会话:**
```bash
sudo tee /usr/local/bin/fix-desktop > /dev/null << 'EOF'
#!/bin/bash
echo "正在重启桌面会话(lightdm)..."
sudo systemctl restart lightdm
echo "完成,几秒后小屏自动登录到干净桌面。"
EOF
sudo chmod +x /usr/local/bin/fix-desktop
```

### 知识点:可靠性 > 优雅

`restart lightdm` 会关掉当时开着的图形程序(代价),但 100% 可靠复位整个会话(收益)。
**在特殊/受限环境里,选可靠的粗暴方案,而不是优雅但易出幺蛾子的方案。** 这是一条重要的工程判断经验。

---

## 十三、踩坑总结(快速查阅)

| 坑 | 现象 | 原因 | 解决 |
|---|---|---|---|
| 1 文件名 | `firmware load failed error -2` | bin 名字不是 `panel-mipi-dbi-spi.bin` | 改名 |
| 2 BCM/物理脚 | 接线全错位 | 混淆 BCM 编号和物理引脚号 | 接线看物理脚,配置写 BCM |
| 3 DC 接错 | 软件全正常但黑屏 | DC 接到错误的脚 | 接对 DC |
| 4 黑屏+光标 | 像桌面崩了 | 壁纸丢失+面板溢出 | 设壁纸,确认桌面进程在跑 |
| 5 cookie 报错 | `Invalid MIT-MAGIC-COOKIE` | SSH 操作 :0 缺授权 | 设 XAUTHORITY |
| 6 注销卡死 | 注销后回登录界面 | 自动登录只开机触发 | 用 restart lightdm |

---

## 十四、迁移到别的场景

### 换一块 SPI 屏(如 ILI9341)
- 体检三连不变
- panel.bin 的初始化序列换成新屏 datasheet 的
- config.txt 改 width/height 和 GPIO 号
- 分层验证流程完全一样

### 换发行版(如 Raspberry Pi OS / Debian)
- config.txt 机制通用(都在 /boot/firmware/)
- 自动登录的登录管理器可能不同(GDM/LightDM),配置文件不同
- systemd target 切换通用

### 换接口(SPI → DSI)
- ①③④⑤ 步思路不变
- 第②步变化大:DSI 要写专属 panel 驱动 .c + 设备树,不能用通用驱动
- 需要屏的 datasheet + init code

### 换板子(非树莓派,如 RK3568)
- config.txt 机制不适用,改为直接编辑设备树源文件
- 但"指定 compatible + 接线 + 分辨率 + 初始化序列"的本质完全一样
- 工业产品里这些会被打包进 Yocto 的 BSP 配方

---

## 附:命令速查

```bash
# 体检
ls /boot/firmware/overlays/ | grep mipi
modinfo panel-mipi-dbi
uname -r

# 做 panel.bin
python3 mipi-dbi-cmd panel.bin panel.txt
sudo cp panel.bin /lib/firmware/panel-mipi-dbi-spi.bin

# 验证
ls /dev/fb*
cat /sys/class/graphics/fb0/name
sudo dmesg | grep -iE "mipi|panel"
cat /dev/urandom | sudo tee /dev/fb0 > /dev/null   # 雪花测试

# 模式切换
display-mode status
sudo systemctl restart lightdm   # 桌面急救
```

---

*本笔记基于一次真实的点屏实操整理。核心不是命令,而是"五步方法论 + 分层验证心法 + 六个坑的教训"。*