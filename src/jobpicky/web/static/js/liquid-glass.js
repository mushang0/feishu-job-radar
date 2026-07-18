// Web liquid-glass approximation adapted from rdev/liquid-glass-react (MIT).
// React state is replaced with one delegated, requestAnimationFrame-throttled listener.
const DYNAMIC_SELECTOR = ".topbar, .home-radar-card, .job-modal-card";

export function initLiquidGlass() {
  const root = document.documentElement;
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const reduceTransparency = matchMedia("(prefers-reduced-transparency: reduce)");
  const supportsBackdrop = CSS.supports("backdrop-filter", "blur(1px)") || CSS.supports("-webkit-backdrop-filter", "blur(1px)");
  root.dataset.glass = supportsBackdrop && !reduceTransparency.matches ? "full" : "fallback";
  if (!supportsBackdrop || reduceMotion.matches || reduceTransparency.matches) return () => {};

  let active = null;
  let bounds = null;
  let frame = 0;
  let point = { x: 0, y: 0 };

  const activate = target => {
    const glass = target.closest?.(DYNAMIC_SELECTOR);
    if (glass === active) return;
    active?.classList.remove("glass-pointer-active");
    active = glass;
    bounds = active?.getBoundingClientRect() || null;
    active?.classList.add("glass-pointer-active");
  };

  const render = () => {
    frame = 0;
    if (!active || !bounds) return;
    const x = Math.max(-1, Math.min(1, (point.x - (bounds.left + bounds.width / 2)) / Math.max(bounds.width / 2, 1)));
    const y = Math.max(-1, Math.min(1, (point.y - (bounds.top + bounds.height / 2)) / Math.max(bounds.height / 2, 1)));
    active.style.setProperty("--glass-x", x.toFixed(3));
    active.style.setProperty("--glass-y", y.toFixed(3));
  };

  const onPointerMove = event => {
    point = { x: event.clientX, y: event.clientY };
    activate(event.target);
    if (!frame) frame = requestAnimationFrame(render);
  };

  const onPointerOut = event => {
    if (event.relatedTarget?.closest?.(DYNAMIC_SELECTOR) === active) return;
    active?.classList.remove("glass-pointer-active");
    active = null;
    bounds = null;
  };

  document.addEventListener("pointermove", onPointerMove, { passive: true });
  document.addEventListener("pointerout", onPointerOut, { passive: true });
  return () => {
    document.removeEventListener("pointermove", onPointerMove);
    document.removeEventListener("pointerout", onPointerOut);
    if (frame) cancelAnimationFrame(frame);
  };
}
