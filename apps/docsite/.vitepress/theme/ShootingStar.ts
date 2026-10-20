import { defineComponent, h, onMounted, onUnmounted, ref } from 'vue';

const STAR_DURATION = 1200;
const SPAWN_INTERVAL = 8400;
const TAIL_MAX = 18;
const HEAD_RADIUS = 1.6;
const TAIL_MAX_RADIUS = 1.4;

interface ShootingStar {
  p0: { x: number; y: number };
  p1: { x: number; y: number };
  p2: { x: number; y: number };
  startTime: number;
  trail: { x: number; y: number }[];
}

export default defineComponent({
  name: 'ShootingStar',
  setup() {
    const canvas = ref<HTMLCanvasElement | null>(null);
    const mouse = { x: -1000, y: -1000 };
    const stars: ShootingStar[] = [];
    let animId = 0;
    let spawnTimer: null | ReturnType<typeof setInterval> = null;

    function bezier(t: number, p0: number, p1: number, p2: number): number {
      const u = 1 - t;
      return u * u * p0 + 2 * u * t * p1 + t * t * p2;
    }

    function bezierPoint(
      t: number,
      star: ShootingStar,
    ): { x: number; y: number } {
      return {
        x: bezier(t, star.p0.x, star.p1.x, star.p2.x),
        y: bezier(t, star.p0.y, star.p1.y, star.p2.y),
      };
    }

    function spawnStar() {
      const el = canvas.value;
      if (!el) return;
      const w = el.width;
      const h = el.height;

      const mx = Math.max(20, Math.min(w - 20, mouse.x));
      const my = Math.max(20, Math.min(h - 20, mouse.y));

      const slope = -h / w;
      const lineY = (x: number) => my + slope * (x - mx);

      const base =
        Math.random() < 0.5
          ? { x: -(Math.random() * 120 + 40), y: Math.random() * h * 0.4 }
          : { x: Math.random() * w * 0.4, y: -(Math.random() * 80 + 30) };
      const by = lineY(base.x);
      const p0 = {
        x: base.x,
        y: Math.min(base.y, by - (Math.random() * 60 + 20)),
      };

      const tip =
        Math.random() < 0.5
          ? {
              x: w + Math.random() * 120 + 40,
              y: h * 0.6 + Math.random() * h * 0.4,
            }
          : {
              x: w * 0.6 + Math.random() * w * 0.4,
              y: h + Math.random() * 80 + 30,
            };
      const ty = lineY(tip.x);
      const p2 = {
        x: tip.x,
        y: Math.max(tip.y, ty + (Math.random() * 60 + 20)),
      };

      stars.push({
        p0,
        p1: { x: mx, y: my },
        p2,
        startTime: performance.now(),
        trail: [],
      });
    }

    function drawStar(
      ctx: CanvasRenderingContext2D,
      star: ShootingStar,
      progress: number,
    ) {
      const pt = bezierPoint(progress, star);
      star.trail.push(pt);
      if (star.trail.length > TAIL_MAX) star.trail.shift();

      const fade = 1 - progress;
      const trail = star.trail;

      for (const [i, point] of trail.entries()) {
        const t = i / trail.length;
        const alpha = t * fade * 0.28;
        const radius = TAIL_MAX_RADIUS * t;
        ctx.beginPath();
        ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(75, 121, 236, ${alpha})`;
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(pt.x, pt.y, HEAD_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255, 255, 255, ${fade * 0.3})`;
      ctx.fill();

      ctx.beginPath();
      ctx.arc(pt.x, pt.y, HEAD_RADIUS + 6, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(75, 121, 236, ${fade * 0.25})`;
      ctx.fill();
    }

    function animate() {
      const el = canvas.value;
      if (!el) return;
      const ctx = el.getContext('2d');
      if (!ctx) return;

      ctx.clearRect(0, 0, el.width, el.height);

      const now = performance.now();

      for (let i = stars.length - 1; i >= 0; i--) {
        const star = stars[i];
        if (!star) continue;
        const elapsed = now - star.startTime;
        const progress = Math.min(elapsed / STAR_DURATION, 1);
        const eased =
          progress < 0.5
            ? 2 * progress * progress
            : -1 + (4 - 2 * progress) * progress;

        if (progress >= 1) {
          stars.splice(i, 1);
          continue;
        }

        drawStar(ctx, star, eased);
      }

      animId = requestAnimationFrame(animate);
    }

    function onMouseMove(e: MouseEvent) {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    }

    function onResize() {
      const el = canvas.value;
      if (!el) return;
      el.width = window.innerWidth;
      el.height = window.innerHeight;
    }

    onMounted(() => {
      onResize();
      window.addEventListener('resize', onResize);
      window.addEventListener('mousemove', onMouseMove);
      spawnTimer = setInterval(spawnStar, SPAWN_INTERVAL);
      animId = requestAnimationFrame(animate);
    });

    onUnmounted(() => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('mousemove', onMouseMove);
      if (spawnTimer !== null) clearInterval(spawnTimer);
      cancelAnimationFrame(animId);
    });

    return () => h('canvas', { ref: canvas, class: 'shooting-star-canvas' });
  },
});
