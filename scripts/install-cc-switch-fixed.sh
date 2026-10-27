#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install-cc-switch-fixed.sh
#
# 把 CC Switch 的 AppImage 安装成"使用系统 GTK3/WebKitGTK"的修复版。
#
# 背景：CC Switch v4.0.12 的 AppImage 内置了构建机 (Ubuntu 22.04) 的整套
# GTK3 / GLib 2.72 / WebKitGTK 库。在 Ubuntu 26.04 + Mesa 26 上，这套旧库
# 创建 EGL display 失败 (EGL_BAD_PARAMETER)，旧版 WebKit 在该分支直接
# CRASH()，导致 WebKitWebProcess abort、窗口白屏。
#
# 本脚本做的事：
#   1. 解包 AppImage
#   2. 删除内置的整套共享库（改用系统 GTK3/WebKitGTK 2.52.6）
#   3. 写一个极简 AppRun
#   4. 安装到补全后的目录，并创建桌面菜单项
#
# 用法：
#   ./install-cc-switch-fixed.sh <AppImage路径> <父目录> [--force]
#
#   两个参数都必填。第二个参数是**父目录**，实际安装目录会自动补全为
#     <父目录>/<AppImage 文件名去掉 .AppImage>
#
# 例：
#   ./install-cc-switch-fixed.sh \
#       ~/Downloads/CC-Switch-v4.0.12-Linux-x86_64.AppImage \
#       ~/Applications
#
#   实际安装到：~/Applications/CC-Switch-v4.0.12-Linux-x86_64
#   启动方式  ：<安装目录>/AppRun
# ---------------------------------------------------------------------------
set -euo pipefail

usage() {
    cat >&2 <<EOF
用法: $0 <AppImage路径> <父目录> [--force]

  AppImage路径  例如 ~/Downloads/CC-Switch-v4.0.12-Linux-x86_64.AppImage
  父目录        必填，例如 ~/Applications
                实际安装目录 = <父目录>/<AppImage 文件名去掉 .AppImage>
                即 ~/Applications/CC-Switch-v4.0.12-Linux-x86_64
  --force       实际安装目录已存在且非空时，允许覆盖

例:
  $0 ~/Downloads/CC-Switch-v4.0.12-Linux-x86_64.AppImage \\
     ~/Applications
EOF
}

FORCE=0
ARGS=()
for a in "$@"; do
    case "$a" in
        --force)   FORCE=1 ;;
        -h|--help) usage; exit 0 ;;
        *)         ARGS+=("$a") ;;
    esac
done

if [ "${#ARGS[@]}" -ne 2 ]; then
    echo "!! 需要且仅需要两个参数：<AppImage路径> <父目录>" >&2
    usage
    exit 1
fi

APPIMAGE="${ARGS[0]}"
PARENT="${ARGS[1]}"

# 展开可能未被 shell 展开的 ~
case "$APPIMAGE" in "~"*) APPIMAGE="$HOME${APPIMAGE#\~}" ;; esac
case "$PARENT"   in "~"*) PARENT="$HOME${PARENT#\~}"     ;; esac

[ -f "$APPIMAGE" ] || { echo "!! AppImage 不存在: $APPIMAGE" >&2; exit 1; }
[ -n "$PARENT" ]   || { echo "!! 父目录不能为空" >&2; exit 1; }

APPIMAGE="$(readlink -f "$APPIMAGE")"
# AppImage 文件名去掉 .AppImage 后缀，作为安装目录名
APPNAME="$(basename "$APPIMAGE" .AppImage)"
[ -n "$APPNAME" ] || { echo "!! 无法从文件名推导安装目录名: $APPIMAGE" >&2; exit 1; }

# 规范化父目录（可能还不存在）
mkdir -p "$PARENT"
PARENT="$(readlink -f "$PARENT")"
DEST="$PARENT/$APPNAME"

case "$DEST" in
    "/"|"$HOME"|"$HOME/") echo "!! 拒绝安装到 $DEST" >&2; exit 1 ;;
esac

if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null || true)" ] && [ "$FORCE" != 1 ]; then
    echo "!! 安装目录已存在且非空: $DEST" >&2
    echo "   如需覆盖，请加 --force" >&2
    exit 1
fi

echo "==> AppImage : $APPIMAGE"
echo "==> 父目录   : $PARENT"
echo "==> 安装到   : $DEST"

# --- 依赖检查 -------------------------------------------------------------
missing=0
for lib in libwebkit2gtk-4.1.so.0 libgtk-3.so.0 libsoup-3.0.so.0 libayatana-appindicator3.so.1; do
    if ! ls /usr/lib/*/"$lib" >/dev/null 2>&1; then
        echo "!! 缺少系统库: $lib" >&2
        missing=1
    fi
done
if [ "$missing" = 1 ]; then
    echo "!! 请先安装: sudo apt install libwebkit2gtk-4.1-0 libgtk-3-0 libsoup-3.0-0 libayatana-appindicator3-1 glib-networking" >&2
    exit 1
fi

# --- 解包 -----------------------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "==> 解包中（约 100 MB，需要一点时间）..."
( cd "$WORK" && "$APPIMAGE" --appimage-extract >/dev/null )
APPDIR="$WORK/squashfs-root"
[ -d "$APPDIR" ] || { echo "!! 解包失败" >&2; exit 1; }

# --- 删除内置共享库，只保留 WebKit helper 桩 ------------------------------
echo "==> 移除内置 GTK/GLib/WebKit 库（改用系统库）..."
find "$APPDIR/usr/lib" -mindepth 1 -maxdepth 1 ! -name 'x86_64-linux-gnu' -exec rm -rf {} +
if [ -d "$APPDIR/usr/lib/x86_64-linux-gnu" ]; then
    find "$APPDIR/usr/lib/x86_64-linux-gnu" -mindepth 1 -maxdepth 1 \
         ! -name 'webkit2gtk-4.1' -exec rm -rf {} +
fi
rm -rf "$APPDIR/apprun-hooks" "$APPDIR/AppRun.wrapped"

# --- 极简 AppRun ----------------------------------------------------------
cat > "$APPDIR/AppRun" <<'EOS'
#!/usr/bin/env bash
# 修复版启动器：直接使用系统的 GTK3 / WebKitGTK，避免内置旧库与 Mesa 26 冲突
set -e
this_dir="$(readlink -f "$(dirname "$0")")"
exec "$this_dir/usr/bin/cc-switch" "$@"
EOS
chmod +x "$APPDIR/AppRun"

# --- 安装 -----------------------------------------------------------------
echo "==> 安装到 $DEST ..."
rm -rf "$DEST"
mv "$APPDIR" "$DEST"

# --- 桌面菜单项 -----------------------------------------------------------
ICON=""
for cand in "$DEST/CC Switch.png" "$DEST/cc-switch.png" \
            "$DEST/usr/share/icons/hicolor/256x256/apps/cc-switch.png"; do
    [ -f "$cand" ] && ICON="$cand" && break
done

NAME="CC Switch"

# 菜单项固定为 CC-Switch.desktop；不写 MimeType，ccswitch:// 深链交给应用自身注册的 handler。
DESKTOP="$HOME/.local/share/applications/CC-Switch.desktop"
mkdir -p "$(dirname "$DESKTOP")"
cat > "$DESKTOP" <<EOS
[Desktop Entry]
Type=Application
Name=$NAME
Comment=All-in-One Assistant for Claude Code, Codex & Gemini CLI
Exec=$DEST/AppRun
Icon=$ICON
Terminal=false
Categories=Utility;
StartupWMClass=cc-switch
EOS

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

cat <<EOS

完成。

  安装目录 : $DEST
  菜单项   : $DESKTOP
  启动命令 : $DEST/AppRun

提示：v4 使用 DBus 单实例锁，请先退出其它正在运行的 CC Switch 实例。
EOS
