/* Safari's Page Zoom also shrinks the font used for input-focus assistance.
   Keep editable text at least 16 rendered pixels without restricting pinch zoom.
   The layout viewport / physical width ratio tracks Page Zoom; unlike
   innerWidth and visualViewport.scale, it does not follow a pinch gesture. */
(function () {
  'use strict';

  const phone = /iPhone|iPod/.test(navigator.userAgent) || /iPhone|iPod/.test(navigator.platform);
  const ios = phone || /iPad/.test(navigator.userAgent) ||
    navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  if (!ios) return;

  const root = document.documentElement;
  let previousFloor;

  function physicalWidth() {
    // iPhone Safari can retain pre-rotation outer dimensions until reload.
    // Screen dimensions and orientation stay reliable across that rotation.
    // iPad retains the window width so split view is measured independently.
    const screen = window.screen;
    const type = screen?.orientation?.type;
    const angle = window.orientation;
    const landscape = type?.startsWith('landscape') ? true : type?.startsWith('portrait') ? false :
      Number.isFinite(angle) && angle % 90 === 0 ? Math.abs(angle) % 180 === 90 : null;
    if (phone && landscape !== null && Number.isFinite(screen?.width) && Number.isFinite(screen?.height) &&
        screen.width > 0 && screen.height > 0) {
      return landscape ? Math.max(screen.width, screen.height) : Math.min(screen.width, screen.height);
    }
    return window.outerWidth;
  }

  function updateFontFloor() {
    const layoutWidth = root.clientWidth;
    const windowWidth = physicalWidth();
    const ratio = Number.isFinite(layoutWidth) && Number.isFinite(windowWidth) &&
      layoutWidth > 0 && windowWidth > 0 ? layoutWidth / windowWidth : 1;
    const floor = Math.max(16, Math.ceil(16 * ratio));
    if (floor === previousFloor) return;
    root.style.setProperty('--touch-form-font-floor', `${floor}px`, 'important');
    previousFloor = floor;
  }

  updateFontFloor();
  window.addEventListener('resize', updateFontFloor, { passive: true });
  window.addEventListener('orientationchange', updateFontFloor, { passive: true });
  // Safari's Page Zoom menu can resize the viewport without a window resize.
  // A pinch may trigger this too; the layout/window ratio stays unchanged.
  window.visualViewport?.addEventListener('resize', updateFontFloor, { passive: true });
  // Refresh before the default focus action if a viewport event was delayed.
  document.addEventListener('pointerdown', updateFontFloor, { capture: true, passive: true });
  document.addEventListener('touchstart', updateFontFloor, { capture: true, passive: true });
  document.addEventListener('DOMContentLoaded', updateFontFloor, { once: true });
})();
