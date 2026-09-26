(() => {
  const canvas = document.getElementById("particles");
  const context = canvas?.getContext("2d");
  if (!context) return;
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let width = 0, height = 0, points = [], frame = 0, previous = 0;
  function draw(delta) {
    context.clearRect(0, 0, width, height);
    for (const point of points) {
      point.y -= point.speed * delta;
      point.x += point.drift * delta;
      if (point.y < -10) point.y = height + 10;
      if (point.x < -10) point.x = width + 10;
      if (point.x > width + 10) point.x = -10;
      context.fillStyle = `rgba(145, 242, 205, ${point.alpha})`;
      context.beginPath();
      context.arc(point.x, point.y, point.radius, 0, Math.PI * 2);
      context.fill();
    }
  }
  function resize() {
    width = window.innerWidth;
    height = window.innerHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    points = Array.from({length: width < 620 ? 28 : 64}, () => ({
      x: Math.random() * width, y: Math.random() * height,
      radius: .7 + Math.random() * 1.4, speed: 5 + Math.random() * 9,
      drift: (Math.random() - .5) * 5, alpha: .15 + Math.random() * .35,
    }));
    draw(0);
  }
  function tick(time) {
    draw(previous ? Math.min((time - previous) / 1000, .05) : 0);
    previous = time;
    frame = requestAnimationFrame(tick);
  }
  function syncMotion() {
    cancelAnimationFrame(frame);
    previous = 0;
    if (!document.hidden && !motion.matches) frame = requestAnimationFrame(tick);
    else draw(0);
  }
  window.addEventListener("resize", resize, {passive: true});
  document.addEventListener("visibilitychange", syncMotion);
  motion.addEventListener("change", syncMotion);
  resize();
  syncMotion();
})();
