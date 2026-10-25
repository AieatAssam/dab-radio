/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V5 */
(() => {
  "use strict";
  const modes = ["LED Spectrum", "Mirror Spectrum", "Oscilloscope", "Radial Corona", "Flowing Ribbon", "Spectrogram"];
  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));

  function create(canvas, options = {}) {
    const win = canvas.ownerDocument.defaultView;
    const ctx = canvas.getContext("2d", { alpha: false });
    const analyser = () => options.getAnalyser?.() || null;
    const reduced = win.matchMedia?.("(prefers-reduced-motion: reduce)");
    let bins = new Uint8Array(0), wave = new Uint8Array(0), fftSize = 0;
    const specW = 128, specH = 48;
    const history = new Uint8Array(specW * specH);
    const specCanvas = canvas.ownerDocument.createElement("canvas");
    specCanvas.width = specW; specCanvas.height = specH;
    const specCtx = specCanvas.getContext("2d", { alpha: false });
    const specImage = specCtx?.createImageData(specW, specH);
    let mode = clamp(Math.trunc(Number(options.mode) || 0), 0, modes.length - 1), raf = 0, alive = false;
    let w = 0, h = 0, frame = 0, lastDraw = 0;
    let colors = { green: "", amber: "", bg: "", dim: "" };
    let greenRGB = [0, 0, 0], amberRGB = [0, 0, 0], backgroundRGB = [0, 0, 0];
    const probe = canvas.ownerDocument.createElement("canvas");
    probe.width = probe.height = 1;
    const probeCtx = probe.getContext("2d", { willReadFrequently: true });
    const rgb = (color) => {
      if (!probeCtx) return [0, 0, 0];
      probeCtx.fillStyle = color; probeCtx.fillRect(0, 0, 1, 1);
      return probeCtx.getImageData(0, 0, 1, 1).data;
    };
    const readColors = () => {
      const root = win.getComputedStyle(canvas.ownerDocument.documentElement);
      const openerTheme = window.getComputedStyle(window.document.documentElement);
      const read = (name, previous) => root.getPropertyValue(name).trim() || openerTheme.getPropertyValue(name).trim() || previous || win.getComputedStyle(canvas).color;
      colors.green = read("--color-led-green", read("--color-accent", colors.green));
      colors.amber = read("--color-led-amber", colors.amber);
      colors.bg = read("--color-panel-deep", colors.bg);
      colors.dim = read("--color-line", colors.dim);
      greenRGB = rgb(colors.green); amberRGB = rgb(colors.amber); backgroundRGB = rgb(colors.bg);
    };
    const resize = () => {
      const rect = canvas.getBoundingClientRect(), dpr = Math.min(2, win.devicePixelRatio || 1);
      w = Math.max(1, rect.width); h = Math.max(1, rect.height);
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      if (!ctx) { readColors(); return; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); readColors();
    };
    const clear = () => { ctx.fillStyle = colors.bg; ctx.fillRect(0, 0, w, h); };
    const draw = (now) => {
      raf = 0; if (!alive) return;
      const fps = reduced?.matches ? 8 : mode === 5 ? 15 : 30;
      if (now - lastDraw < 1000 / fps) { raf = win.requestAnimationFrame(draw); return; }
      lastDraw = now;
      const a = analyser(), playing = !!options.isPlaying?.() && a;
      if (!ctx) { raf=win.requestAnimationFrame(draw); return; }
      if (!playing) { clear(); if(mode===5) history.fill(0); }
      else {
        if (fftSize !== a.fftSize || bins.length !== a.frequencyBinCount) {
          fftSize = a.fftSize; bins = new Uint8Array(a.frequencyBinCount); wave = new Uint8Array(a.fftSize);
        }
        const n = bins.length;
        a.getByteFrequencyData(bins); a.getByteTimeDomainData(wave);
        clear();
        const val = i => bins[Math.min(n - 1, Math.floor(Math.pow(i / 128, 1.8) * n))] / 255;
        if (mode === 0 || mode === 1) {
          const count = Math.max(1, Math.floor(w / 4)), mid = h / 2;
          for (let i=0;i<count;i++) { const v=val(Math.floor(i*128/count)), bh=Math.max(1,v*(mode===1?mid:h)); ctx.fillStyle=v>.72?colors.amber:colors.green;
            if(mode===0){ const seg=Math.max(2,h/24); for(let y=h;y>h-bh;y-=seg+1) ctx.fillRect(i*4,y-seg,2,seg); }
            else { ctx.fillRect(i*w/count,mid-bh,w/count-1,bh); ctx.fillRect(i*w/count,mid,w/count-1,bh); }
          }
        } else if (mode === 2) {
          ctx.beginPath(); for(let x=0;x<=Math.ceil(w);x++){const i=Math.min(wave.length-1,Math.floor(x/w*wave.length)), y=wave[i]/255*h; x?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.strokeStyle=colors.green;ctx.lineWidth=1.5;ctx.stroke();
        } else if (mode === 3) {
          const cx=w/2,cy=h/2,r=Math.min(w,h)*.18; ctx.beginPath();
          for(let i=0;i<=128;i++){const t=i/128*Math.PI*2, rr=r+val(i)*Math.min(w,h)*.28, x=cx+Math.cos(t)*rr,y=cy+Math.sin(t)*rr;i?ctx.lineTo(x,y):ctx.moveTo(x,y);} ctx.closePath();ctx.strokeStyle=colors.green;ctx.lineWidth=1.5;ctx.stroke();
        } else if(mode===4) {
          ctx.beginPath(); ctx.moveTo(0,h/2);
          for(let x=0;x<=Math.ceil(w);x++){const i=Math.min(wave.length-1,Math.floor(x/w*wave.length));const y=h/2+(wave[i]-128)/128*h*.42;ctx.lineTo(x,y);}
          ctx.lineTo(w,h/2);ctx.closePath();ctx.fillStyle=colors.green;ctx.globalAlpha=.48;ctx.fill();ctx.globalAlpha=1;
        } else {
          const row=frame%specH, rgb=specImage?.data;
          if (rgb && specCtx) {
            for(let x=0;x<specW;x++) history[row*specW+x]=bins[Math.floor(x*n/specW)]||0;
            for(let y=0;y<specH;y++)for(let x=0;x<specW;x++){
              const v=history[((row-y+specH)%specH)*specW+x], p=(y*specW+x)*4;
              const amber=v>185, strength=v/255;
              const color = amber ? amberRGB : greenRGB;
              for (let channel = 0; channel < 3; channel++) rgb[p + channel] = Math.round(backgroundRGB[channel] * (1 - strength) + color[channel] * strength);
              rgb[p+3]=255;
            }
            specCtx.putImageData(specImage,0,0);ctx.imageSmoothingEnabled=false;ctx.drawImage(specCanvas,0,0,w,h);ctx.imageSmoothingEnabled=true;
          }
        }
      }
      frame++; raf=win.requestAnimationFrame(draw);
    };
    const observer = win.ResizeObserver ? new win.ResizeObserver(resize) : null;
    observer?.observe(canvas); resize();
    const api = { start(){if(!alive){alive=true;raf=win.requestAnimationFrame(draw);}}, stop(){alive=false;if(raf)win.cancelAnimationFrame(raf);raf=0;if(ctx)clear();}, destroy(){api.stop();observer?.disconnect();}, nextMode(){mode=(mode+1)%modes.length;history.fill(0);readColors();options.onModeChange?.(modes[mode],mode);}, get modeName(){return modes[mode];}, get modeIndex(){return mode;} };
    return api;
  }
  window.DABVisualisations = { create };
})();
