#!/usr/bin/env python3
# HB Keyboard patcher: runs on an apktool-decoded folder.
import os, re, sys, glob

D = sys.argv[1].rstrip('/')
LOG = []


def say(tag, msg):
    line = '[%s] %s' % (tag, msg)
    LOG.append(line)
    print(line)


def die(msg):
    say('FAIL', msg)
    sys.exit(1)


def rd(p):
    with open(p, encoding='utf-8', newline='') as f:
        return f.read()


def wr(p, s):
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


# ---------------------------------------------------------------- 1. manifest
mp = D + '/AndroidManifest.xml'
m = rd(mp)
m2 = re.sub(
    r'[ \t]*<uses-permission[^>]*android:name="android\.permission\.(?:INTERNET|FOREGROUND_SERVICE_MEDIA_PROJECTION)"[^>]*/>[ \t]*\r?\n?',
    '', m)
if 'android.permission.INTERNET' in m2:
    die('INTERNET permission is still in the manifest')
wr(mp, m2)
say('OK', 'manifest: INTERNET permission removed (removed=%s)' % (m != m2))

# ------------------------------------------------- 2. app name in resources
n = 0
for p in glob.glob(D + '/res/values*/*.xml'):
    s = rd(p)
    if 'Orbit Board' in s:
        n += s.count('Orbit Board')
        wr(p, s.replace('Orbit Board', 'HB Keyboard'))
say('OK' if n else 'WARN', 'resources: renamed "Orbit Board" -> "HB Keyboard" in %d places' % n)

# ------------------------------------------------------------------- 3. icon
LIGHT = 0xe3   # light grey (tile)
DARKG = 0x4f   # dark grey (pill)


def grey_of(r, g, b):
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return int(round(DARKG + (LIGHT - DARKG) * lum / 255.0))


# 3a. adaptive icon background colour
nb = 0
for p in glob.glob(D + '/res/values*/*.xml'):
    s = rd(p)
    s2 = re.sub(r'(<color name="ic_launcher_background">)[^<]*(</color>)',
                r'\g<1>#ffe3e3e3\g<2>', s)
    if s2 != s:
        wr(p, s2)
        nb += 1
say('OK' if nb else 'WARN', 'icon: adaptive background colour changed in %d file(s)' % nb)


# 3b. adaptive icon foreground (vector)
def remap(mo):
    pre, col, post = mo.group(1), mo.group(2), mo.group(3)
    h = col[1:]
    a, rgb = (h[:2], h[2:]) if len(h) == 8 else ('', h)
    r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    if r > 140 and r - max(g, b) > 60:
        new = 'ffffff'          # red knob -> white
    else:
        v = grey_of(r, g, b)    # everything else -> grey
        new = '%02x%02x%02x' % (v, v, v)
    return pre + '#' + a + new + post


nv = 0
for p in glob.glob(D + '/res/drawable*/ic_launcher_foreground*.xml'):
    s = rd(p)
    s2 = re.sub(r'(android:(?:fillColor|strokeColor)=")(#[0-9a-fA-F]{6,8})(")', remap, s)
    if s2 != s:
        wr(p, s2)
        nv += 1
say('OK' if nv else 'WARN', 'icon: foreground vector recoloured in %d file(s)' % nv)

# 3c. legacy bitmap icons (old Android versions)
try:
    from PIL import Image
    ni = 0
    files = []
    for ext in ('webp', 'png'):
        files += glob.glob(D + '/res/mipmap*/ic_launcher*.' + ext)
    for p in files:
        im = Image.open(p).convert('RGBA')
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                red = max(0.0, r - (g + b) / 2.0)
                k = min(1.0, red / 90.0)
                v = int(round(grey_of(r, g, b) * (1 - k) + 255 * k))
                px[x, y] = (v, v, v, a)
        if p.endswith('.webp'):
            im.save(p, 'WEBP', lossless=True)
        else:
            im.save(p, 'PNG')
        ni += 1
    say('OK' if ni else 'WARN', 'icon: %d legacy bitmap icon(s) recoloured' % ni)
except Exception as e:
    say('WARN', 'icon: legacy bitmaps skipped (%s)' % e)

# ------------------------------------------------------------------ 4. smali
smali_files = []
for sd in glob.glob(D + '/smali*'):
    for dp, _, fs in os.walk(sd):
        for f in fs:
            if f.endswith('.smali'):
                smali_files.append(os.path.join(dp, f))
say('OK', 'smali: %d files found' % len(smali_files))

# 4a. hide the developer card (make the composable return immediately)
patched_card = 0
for p in smali_files:
    if 'DeveloperDetailsCard' not in os.path.basename(p):
        continue
    L = rd(p).split('\n')
    changed = False
    i = 0
    while i < len(L):
        if re.match(r'^\.method .* DeveloperDetailsCard\(.*\)V\s*$', L[i]):
            j = i + 1
            in_ann = False
            while j < len(L):
                t = L[j].strip()
                if t.startswith('.annotation'):
                    in_ann = True
                    j += 1
                    continue
                if t.startswith('.end annotation'):
                    in_ann = False
                    j += 1
                    continue
                if in_ann or t == '' or t.startswith(('.locals', '.registers', '.param', '.end param', '.local ')):
                    j += 1
                    continue
                break
            L.insert(j, '    return-void')
            changed = True
            patched_card += 1
            i = j + 1
        i += 1
    if changed:
        wr(p, '\n'.join(L))
say('OK' if patched_card else 'WARN',
    'developer card: %d method(s) set to return immediately' % patched_card)

# 4b. text / link replacements inside string constants
EXACT = {
    'About Orbit Board': 'About HB Keyboard (customized by Hasib B. Hasan)',
}
TRIGGERS = ('Orbit Board', 'Fahim Takrim', 'fahitakrim', 'TakrimFahim',
            'facebook.com/profile.php', 'itz.takrim')
LINE = re.compile(
    r'^(\s*(?:const-string(?:/jumbo)?\s+[vp]\d+,\s*|\.field\b[^=\n]*=\s*))"((?:[^"\\]|\\.)*)"(\s*)$')


def fix(sv):
    if sv in EXACT:
        return EXACT[sv]
    if re.search(r'fahitakrim|TakrimFahim|facebook\.com/profile\.php', sv):
        return ''
    sv = sv.replace('itz.takrim@gmail.com', '')
    sv = sv.replace('Fahim Takrim', 'Customized by Hasib B. Hasan')
    sv = sv.replace('Orbit Board', 'HB Keyboard')
    return sv


nstr = 0
for p in smali_files:
    s = rd(p)
    if not any(t in s for t in TRIGGERS):
        continue
    out = []
    ch = False
    for line in s.split('\n'):
        mo = LINE.match(line)
        if mo:
            new = fix(mo.group(2))
            if new != mo.group(2):
                line = mo.group(1) + '"' + new + '"' + mo.group(3)
                nstr += 1
                ch = True
        out.append(line)
    if ch:
        wr(p, '\n'.join(out))
say('OK' if nstr else 'WARN', 'strings: %d string constant(s) rewritten (names, links, email)' % nstr)

# ------------------------------------------------------------ 5. leftovers
left = 0
for p in smali_files:
    s = rd(p)
    for t in ('fahitakrim', 'TakrimFahim', 'itz.takrim', 'facebook.com/profile.php'):
        if t in s:
            left += 1
            say('WARN', 'leftover "%s" in %s' % (t, os.path.relpath(p, D)))
if left == 0:
    say('OK', 'no developer links/emails left in code')

with open('patch-report.txt', 'w') as f:
    f.write('\n'.join(LOG) + '\n')
