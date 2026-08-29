# ORCH-401 + ORCH-402 + ORCH-403 + ORCH-404 + ORCH-405: one cheap persistent
# Linux desktop (Windows-like XFCE + apps) with a localhost noVNC view of THIS
# display (Xvfb :1). xdotool/scrot let Jarvis look/click/type here. Not a
# second machine. Live notepad proof script is ORCH-406.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    DISPLAY=:1 \
    HOME=/home/jarvis \
    USER=jarvis

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb \
        dbus-x11 \
        xfce4-session \
        xfwm4 \
        xfdesktop4 \
        xfce4-panel \
        xfce4-settings \
        gtk2-engines-pixbuf \
        fonts-dejavu-core \
        fonts-liberation \
        ca-certificates \
        chromium \
        mousepad \
        thunar \
        xfce4-terminal \
        galculator \
        ristretto \
        x11vnc \
        novnc \
        websockify \
        xdotool \
        scrot \
        unzip \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/bash jarvis

COPY theme /usr/src/jarvis-windows-theme
RUN mkdir -p \
        /usr/share/themes/JarvisWin \
        /usr/share/icons/JarvisWin \
        /usr/share/backgrounds/jarvis \
        /etc/xdg/xfce4/xfconf/xfce-perchannel-xml \
    && cp /usr/src/jarvis-windows-theme/index.theme /usr/share/themes/JarvisWin/index.theme \
    && cp -a /usr/src/jarvis-windows-theme/gtk-2.0 /usr/share/themes/JarvisWin/ \
    && cp -a /usr/src/jarvis-windows-theme/gtk-3.0 /usr/share/themes/JarvisWin/ \
    && cp -a /usr/src/jarvis-windows-theme/xfwm4 /usr/share/themes/JarvisWin/ \
    && cp -a /usr/src/jarvis-windows-theme/icons/. /usr/share/icons/JarvisWin/ \
    && cp /usr/src/jarvis-windows-theme/wallpaper.png /usr/share/backgrounds/jarvis/windows-like.png \
    && cp /usr/src/jarvis-windows-theme/xfce-config/*.xml /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/ \
    && chmod -R a+rX /usr/share/themes/JarvisWin /usr/share/icons/JarvisWin /usr/share/backgrounds/jarvis

COPY apps /usr/share/jarvis-computer/apps
COPY bin/chrome /usr/local/bin/chrome
# Vendored official uBlock Origin Lite (MV3) zip. Unpacked here; never fetched at start.
# Debian bookworm Chromium 149+ hard-blocks MV2, so the 1.74.0 tree cannot load.
# The GitHub zip has no _metadata/generated_indexed_rulesets. Debian Chromium
# writes those next to the unpacked tree on first load. If that directory is
# root-owned 644/755 (jarvis cannot write), load fails with
# "ublock-filters.json: Internal error while parsing rules." and the extension
# never lists. chown the tree to jarvis so indexing can succeed.
COPY extensions/ublock/uBOLite_2026.825.1619.chromium.zip /tmp/ublock-chromium.zip
COPY policies/managed/ublock.json /etc/chromium/policies/managed/ublock.json
COPY chromium.d/ublock-origin /etc/chromium.d/ublock-origin
RUN chmod 0755 /usr/local/bin/chrome \
    && mkdir -p /usr/share/applications \
        /usr/share/chromium/extensions/ublock \
        /etc/chromium/policies/managed \
        /etc/chromium.d \
    && unzip -q /tmp/ublock-chromium.zip -d /usr/share/chromium/extensions/ublock \
    && test -f /usr/share/chromium/extensions/ublock/manifest.json \
    && rm -f /tmp/ublock-chromium.zip \
    && chmod 0644 /etc/chromium/policies/managed/ublock.json \
        /etc/chromium.d/ublock-origin \
    && mkdir -p /usr/share/chromium/extensions/ublock/_metadata \
    && chown -R jarvis:jarvis /usr/share/chromium/extensions/ublock \
    && chmod -R u+rwX,go+rX /usr/share/chromium/extensions/ublock \
    && cp /usr/share/jarvis-computer/apps/*.desktop /usr/share/applications/ \
    && chmod 0644 /usr/share/applications/chrome.desktop \
        /usr/share/applications/notepad.desktop \
        /usr/share/applications/files.desktop \
        /usr/share/applications/terminal.desktop \
        /usr/share/applications/calculator.desktop \
        /usr/share/applications/image-viewer.desktop \
    && chmod -R a+rX /usr/share/jarvis-computer/apps

COPY novnc/index.html /usr/share/novnc/index.html
COPY entrypoint.sh /usr/local/bin/jarvis-computer-entrypoint.sh
RUN chmod 0755 /usr/local/bin/jarvis-computer-entrypoint.sh \
    && chmod 0644 /usr/share/novnc/index.html

WORKDIR /home/jarvis
ENTRYPOINT ["/usr/local/bin/jarvis-computer-entrypoint.sh"]
