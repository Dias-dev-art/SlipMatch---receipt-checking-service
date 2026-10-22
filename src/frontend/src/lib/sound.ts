// Short two-tone chime for "Check payment", generated with Web Audio (no audio file needed).
// Browsers only allow sound after the user has interacted with the page once.

let ctx: AudioContext | null = null;

export function playPaymentAlert() {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    const start = ctx.currentTime;
    [880, 1320].forEach((frequency, i) => {
      const t = start + i * 0.18;
      const osc = ctx!.createOscillator();
      const gain = ctx!.createGain();
      osc.type = "sine";
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.3, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
      osc.connect(gain).connect(ctx!.destination);
      osc.start(t);
      osc.stop(t + 0.18);
    });
  } catch {
    // No audio support: the toast is still shown.
  }
}
