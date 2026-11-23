(() => {
  const hero = document.querySelector('.cinema-hero');
  if (!hero) return;

  const canDrift = matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)');
  const scene = hero.querySelector('.cinema-scene');
  let frame = 0;

  function resetDrift() {
    cancelAnimationFrame(frame);
    scene.style.removeProperty('--drift-x');
    scene.style.removeProperty('--drift-y');
  }

  hero.addEventListener('pointermove', event => {
    if (!canDrift.matches || event.pointerType !== 'mouse') return;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const bounds = hero.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - .5;
      const y = (event.clientY - bounds.top) / bounds.height - .5;
      scene.style.setProperty('--drift-x', (x * -16).toFixed(2) + 'px');
      scene.style.setProperty('--drift-y', (y * -10).toFixed(2) + 'px');
    });
  }, {passive: true});

  hero.addEventListener('pointerleave', resetDrift);
  canDrift.addEventListener('change', resetDrift);
})();
