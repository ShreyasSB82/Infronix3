import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';

function normalize(vx, vz) {
    const len = Math.hypot(vx, vz) || 1;
    return [vx / len, vz / len];
}

function distPointToSegment(px, pz, ax, az, bx, bz) {
    const abx = bx - ax;
    const abz = bz - az;
    const abLen2 = abx * abx + abz * abz || 1;
    const t = Math.max(0, Math.min(1, ((px - ax) * abx + (pz - az) * abz) / abLen2));
    const sx = ax + abx * t;
    const sz = az + abz * t;
    return Math.hypot(px - sx, pz - sz);
}

/**
 * Creates an opening descriptor mapped to nearest wall descriptor.
 */
export function mapOpeningsToWalls(openings, wallDescriptors, type, defaults = {}) {
    if (!Array.isArray(openings) || !openings.length || !wallDescriptors.length) return [];

    return openings
        .map((o, idx) => {
            const pos = o.pos || o.position;
            if (!Array.isArray(pos) || pos.length < 2) return null;
            const px = Number(pos[0]);
            const pz = Number(pos[1]);

            let nearest = null;
            let minDist = Number.POSITIVE_INFINITY;
            for (const w of wallDescriptors) {
                const d = distPointToSegment(px, pz, w.start.x, w.start.z, w.end.x, w.end.z);
                if (d < minDist) {
                    minDist = d;
                    nearest = w;
                }
            }
            if (!nearest || minDist > (defaults.wallSnapTolerance || 0.8)) return null;
            const [nx, nz] = Array.isArray(o.normal) ? normalize(o.normal[0], o.normal[1]) : [nearest.normal.x, nearest.normal.z];

            return {
                id: `${type}_${idx}`,
                type,
                wallId: nearest.id,
                position: [px, pz],
                width: Number(o.width || defaults.width || 1),
                height: Number(o.height || defaults.height || 1.2),
                elevation: Number(o.elevation || defaults.elevation || 0),
                depth: defaults.depth || defaults.thickness || 0.2,
                normal: [nx, nz],
            };
        })
        .filter(Boolean);
}

export function createOpeningVisual(opening, floorOffset, material) {
    const g = new THREE.BoxGeometry(opening.width, opening.height, Math.max(0.05, opening.depth * 0.7));
    const m = new THREE.Mesh(g, material);
    m.position.set(opening.position[0], floorOffset + opening.elevation + opening.height / 2, opening.position[1]);
    return m;
}
