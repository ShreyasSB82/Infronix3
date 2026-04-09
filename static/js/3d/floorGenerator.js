import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';

function closeRing(coords) {
    if (!Array.isArray(coords) || coords.length < 3) return [];
    const ring = [...coords];
    const f = ring[0];
    const l = ring[ring.length - 1];
    if (f[0] !== l[0] || f[1] !== l[1]) ring.push([f[0], f[1]]);
    return ring;
}

function polygonArea2D(coords) {
    let a = 0;
    for (let i = 0; i < coords.length - 1; i++) {
        const [x1, y1] = coords[i];
        const [x2, y2] = coords[i + 1];
        a += x1 * y2 - x2 * y1;
    }
    return a / 2;
}

function convexHull(points) {
    if (points.length < 3) return points;
    const pts = [...points].sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lower = [];
    for (const p of pts) {
        while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
        lower.push(p);
    }
    const upper = [];
    for (let i = pts.length - 1; i >= 0; i--) {
        const p = pts[i];
        while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
        upper.push(p);
    }
    upper.pop();
    lower.pop();
    const hull = lower.concat(upper);
    return [...hull, hull[0]];
}

/**
 * Detects a boundary polygon from floor data.
 */
export function detectFloorBoundary(floor) {
    if (Array.isArray(floor?.boundary) && floor.boundary.length >= 3) {
        return closeRing(floor.boundary);
    }
    const roomRings = (floor?.rooms || [])
        .map((r) => closeRing(r.coords || []))
        .filter((r) => r.length >= 4);
    if (!roomRings.length) return [];

    // Prefer largest room ring if clearly dominant, otherwise use convex hull.
    const byArea = roomRings
        .map((ring) => ({ ring, area: Math.abs(polygonArea2D(ring)) }))
        .sort((a, b) => b.area - a.area);
    if (byArea.length === 1 || byArea[0].area > byArea[1].area * 1.35) return byArea[0].ring;

    const pts = [];
    roomRings.forEach((ring) => {
        for (let i = 0; i < ring.length - 1; i++) pts.push(ring[i]);
    });
    return convexHull(pts);
}

/**
 * Creates a horizontal slab mesh at a given Y level.
 */
export function createSlab(coords, thickness, material, yLevel = 0) {
    const ring = closeRing(coords);
    if (ring.length < 4) return null;
    const shape = new THREE.Shape();
    shape.moveTo(ring[0][0], ring[0][1]);
    for (let i = 1; i < ring.length; i++) {
        shape.lineTo(ring[i][0], ring[i][1]);
    }

    const geometry = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false, steps: 1 });
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, yLevel, 0);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.receiveShadow = true;

    return mesh;
}
