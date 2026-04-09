import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';

/**
 * Converts a segment to wall descriptor with local axes.
 */
export function buildWallDescriptor(p1, p2, { floorIndex = 0, floorHeight = 3, levelOffset = 0 } = {}) {
    const x1 = Number(p1[0]);
    const z1 = Number(p1[1]);
    const x2 = Number(p2[0]);
    const z2 = Number(p2[1]);
    const dx = x2 - x1;
    const dz = z2 - z1;
    const length = Math.hypot(dx, dz);
    if (!Number.isFinite(length) || length <= 1e-6) return null;

    const dir = new THREE.Vector3(dx / length, 0, dz / length);
    const normal = new THREE.Vector3(-dir.z, 0, dir.x);
    const center = new THREE.Vector3((x1 + x2) / 2, levelOffset + floorHeight / 2, (z1 + z2) / 2);
    return {
        id: `f${floorIndex}_w_${x1.toFixed(3)}_${z1.toFixed(3)}_${x2.toFixed(3)}_${z2.toFixed(3)}`,
        start: new THREE.Vector3(x1, levelOffset, z1),
        end: new THREE.Vector3(x2, levelOffset, z2),
        center,
        dir,
        normal,
        length,
        floorIndex,
        levelOffset,
    };
}

function createBaseWallMesh(descriptor, height, thickness, material) {
    const geom = new THREE.BoxGeometry(descriptor.length, height, thickness);
    const mesh = new THREE.Mesh(geom, material);
    mesh.position.copy(descriptor.center);
    mesh.rotation.y = -Math.atan2(descriptor.dir.z, descriptor.dir.x);
    mesh.updateMatrixWorld(true);
    return mesh;
}

function sortOpeningsByWall(wallOpenings, descriptor) {
    if (!wallOpenings?.length) return [];
    return wallOpenings
        .map((o) => {
            const p = new THREE.Vector3(o.position[0], 0, o.position[1]);
            const rel = p.sub(descriptor.start);
            const along = rel.dot(descriptor.dir);
            return { ...o, along };
        })
        .filter((o) => o.along >= 0 && o.along <= descriptor.length)
        .sort((a, b) => a.along - b.along);
}

/**
 * Creates a wall mesh from a descriptor and cuts door/window holes via CSG.
 */
export function createWallMesh(descriptor, wallOpenings, height, thickness, material) {
    const sortedOpenings = sortOpeningsByWall(wallOpenings, descriptor);
    const startX = -descriptor.length / 2;
    const endX = descriptor.length / 2;

    if (!sortedOpenings.length) return createBaseWallMesh(descriptor, height, thickness, material);

    const wallGroup = new THREE.Group();
    wallGroup.position.copy(descriptor.center);
    wallGroup.rotation.y = -Math.atan2(descriptor.dir.z, descriptor.dir.x);

    const clamped = sortedOpenings.map((o) => {
        const width = Math.max(0.2, o.width || 0.9);
        const heightO = Math.max(0.2, o.height || 2);
        const elev = Math.max(0, o.elevation || 0);
        const c = o.along - descriptor.length / 2;
        return {
            ...o,
            minX: Math.max(startX, c - width / 2),
            maxX: Math.min(endX, c + width / 2),
            openingHeight: Math.min(height, heightO),
            openingElevation: Math.min(height, elev),
        };
    });

    let cursor = startX;
    const addPiece = (xMin, xMax, yMin, yMax) => {
        const w = xMax - xMin;
        const h = yMax - yMin;
        if (w <= 1e-4 || h <= 1e-4) return;
        const g = new THREE.BoxGeometry(w, h, thickness);
        const m = new THREE.Mesh(g, material);
        m.position.set((xMin + xMax) / 2, yMin + h / 2 - height / 2, 0);
        wallGroup.add(m);
    };

    for (const o of clamped) {
        addPiece(cursor, o.minX, 0, height);
        cursor = Math.max(cursor, o.maxX);

        const bottomY = o.openingElevation;
        const topY = Math.min(height, o.openingElevation + o.openingHeight);
        addPiece(o.minX, o.maxX, topY, height); // lintel
        addPiece(o.minX, o.maxX, 0, bottomY);   // sill / lower wall
    }
    addPiece(cursor, endX, 0, height);

    wallGroup.traverse((obj) => {
        if (obj.isMesh) {
            obj.castShadow = true;
            obj.receiveShadow = true;
        }
    });
    return wallGroup;
}

/**
 * Instanced fallback for large wall counts without openings.
 */
export function createInstancedWalls(descriptors, height, thickness, material) {
    if (!descriptors.length) return null;
    const geom = new THREE.BoxGeometry(1, height, thickness);
    const instanced = new THREE.InstancedMesh(geom, material, descriptors.length);
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3(1, 1, 1);
    const axis = new THREE.Vector3(0, 1, 0);

    descriptors.forEach((d, i) => {
        q.setFromAxisAngle(axis, -Math.atan2(d.dir.z, d.dir.x));
        s.set(d.length, 1, 1);
        m.compose(d.center, q, s);
        instanced.setMatrixAt(i, m);
    });
    instanced.instanceMatrix.needsUpdate = true;
    return instanced;
}
