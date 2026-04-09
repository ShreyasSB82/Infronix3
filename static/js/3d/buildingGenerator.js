import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';
import { GLTFExporter } from 'https://unpkg.com/three@0.160.0/examples/jsm/exporters/GLTFExporter.js';
import { buildWallDescriptor, createInstancedWalls, createWallMesh } from './wallGenerator.js';
import { createSlab, detectFloorBoundary } from './floorGenerator.js';
import { createRoof } from './roofGenerator.js';
import { mapOpeningsToWalls, createOpeningVisual } from './doorWindowGenerator.js';

function cloneDeep(obj) {
    return JSON.parse(JSON.stringify(obj));
}

function estimateIsGeographic(floorPlanData) {
    const sample = floorPlanData?.floors?.[0]?.rooms?.[0]?.coords?.[0];
    if (!Array.isArray(sample) || sample.length < 2) return false;
    const [x, y] = sample;
    return Math.abs(x) <= 180 && Math.abs(y) <= 90;
}

function getPlanCenter(floorPlanData) {
    const pts = [];
    (floorPlanData?.floors || []).forEach((f) => {
        (f.rooms || []).forEach((r) => (r.coords || []).forEach((p) => pts.push(p)));
        (f.boundary || []).forEach((p) => pts.push(p));
    });
    if (!pts.length) return [0, 0];
    let sx = 0;
    let sy = 0;
    pts.forEach(([x, y]) => { sx += x; sy += y; });
    return [sx / pts.length, sy / pts.length];
}

function transformPoint(point, center, isGeo) {
    if (!Array.isArray(point) || point.length < 2) return point;
    const [cx, cy] = center;
    const [x, y] = point;
    if (!isGeo) return [x - cx, y - cy];
    const latRad = (cy * Math.PI) / 180;
    const metersPerDegLat = 111320;
    const metersPerDegLon = 111320 * Math.cos(latRad);
    return [(x - cx) * metersPerDegLon, (y - cy) * metersPerDegLat];
}

function normalizeFloorPlanData(input) {
    const floorPlanData = cloneDeep(input);
    const center = getPlanCenter(floorPlanData);
    const isGeo = estimateIsGeographic(floorPlanData);

    (floorPlanData?.floors || []).forEach((floor) => {
        (floor.rooms || []).forEach((room) => {
            room.coords = (room.coords || []).map((p) => transformPoint(p, center, isGeo));
        });
        if (Array.isArray(floor.boundary)) {
            floor.boundary = floor.boundary.map((p) => transformPoint(p, center, isGeo));
        }
        (floor.doors || []).forEach((d) => {
            if (Array.isArray(d.pos)) d.pos = transformPoint(d.pos, center, isGeo);
        });
        (floor.windows || []).forEach((w) => {
            if (Array.isArray(w.pos)) w.pos = transformPoint(w.pos, center, isGeo);
        });
    });
    return floorPlanData;
}

function canonicalWallKey(p1, p2, floorIndex) {
    const a = `${p1[0].toFixed(4)},${p1[1].toFixed(4)}`;
    const b = `${p2[0].toFixed(4)},${p2[1].toFixed(4)}`;
    const [lo, hi] = a < b ? [a, b] : [b, a];
    return `f${floorIndex}:${lo}|${hi}`;
}

function getSiteCenter(sitePlanData) {
    let sx = 0;
    let sy = 0;
    let n = 0;
    (sitePlanData?.zones?.features || []).forEach((f) => {
        const geom = f.geometry;
        if (!geom?.coordinates) return;
        const rings = geom.type === 'MultiPolygon' ? geom.coordinates.flat(1) : geom.coordinates;
        rings.forEach((ring) => {
            if (!Array.isArray(ring)) return;
            ring.forEach((p) => {
                if (Array.isArray(p) && p.length >= 2) {
                    sx += p[0];
                    sy += p[1];
                    n += 1;
                }
            });
        });
    });
    if (!n) return [0, 0];
    return [sx / n, sy / n];
}

function toLocalMeters(point, centerLonLat) {
    const [cx, cy] = centerLonLat;
    const [x, y] = point;
    const isGeo = Math.abs(x) <= 180 && Math.abs(y) <= 90;
    if (!isGeo) return [x - cx, y - cy];
    const latRad = (cy * Math.PI) / 180;
    const metersPerDegLat = 111320;
    const metersPerDegLon = 111320 * Math.cos(latRad);
    return [(x - cx) * metersPerDegLon, (y - cy) * metersPerDegLat];
}

function createShellFromZoneFeature(feature, centerLonLat, floorHeight, material) {
    const geom = feature?.geometry;
    if (!geom?.coordinates) return null;
    const ringRaw = geom.type === 'Polygon'
        ? geom.coordinates?.[0]
        : geom.type === 'MultiPolygon'
            ? geom.coordinates?.[0]?.[0]
            : null;
    if (!Array.isArray(ringRaw) || ringRaw.length < 3) return null;

    const ring = ringRaw.map((p) => toLocalMeters(p, centerLonLat));
    const shape = new THREE.Shape();
    shape.moveTo(ring[0][0], ring[0][1]);
    for (let i = 1; i < ring.length; i++) shape.lineTo(ring[i][0], ring[i][1]);

    const floors = Number(feature?.properties?.num_floors || 1);
    const totalHeight = Math.max(floorHeight, floors * floorHeight);
    const extruded = new THREE.ExtrudeGeometry(shape, { depth: totalHeight, bevelEnabled: false, steps: 1 });
    extruded.rotateX(-Math.PI / 2);
    extruded.translate(0, totalHeight, 0);
    const mesh = new THREE.Mesh(extruded, material);
    mesh.userData.role = 'site-shell';
    return mesh;
}

/**
 * Generates a 3D group containing all buildings for a site plan
 */
export function generate3DSite(sitePlanData, options = {}) {
    const siteGroup = new THREE.Group();
    const shellMaterial = options.shellMaterial || new THREE.MeshStandardMaterial({ color: 0x7ea0bf, transparent: true, opacity: 0.9 });
    const floorHeight = Number(options.floorHeight || 3.0);

    if (!sitePlanData || !sitePlanData.zones || !sitePlanData.zones.features) {
        return siteGroup;
    }

    const centerLonLat = getSiteCenter(sitePlanData);

    sitePlanData.zones.features.forEach(feature => {
        if (feature.properties.zone !== 'building') return;
        if (feature.properties.interior?.floors?.length) {
            const building = generate3DBuilding(feature.properties.interior, options);
            siteGroup.add(building);
            return;
        }
        const shell = createShellFromZoneFeature(feature, centerLonLat, floorHeight, shellMaterial);
        if (shell) siteGroup.add(shell);
    });

    return siteGroup;
}

/**
 * Main function to generate a 3D building from floor plan data.
 * @param {Object} floorPlanData - The JSON from the interior planner.
 * @returns {THREE.Group} - A Three.js group containing the building model.
 */
export function generate3DBuilding(floorPlanData, options = {}) {
    const normalizedData = normalizeFloorPlanData(floorPlanData);
    const buildingGroup = new THREE.Group();
    const FLOOR_HEIGHT = Number(options.floorHeight || 3.0);
    const WALL_THICKNESS = Number(options.wallThickness || 0.2);
    const FLOOR_THICKNESS = Number(options.floorThickness || 0.12);
    const ROOF_THICKNESS = Number(options.roofThickness || 0.16);
    const INSTANCE_WALL_THRESHOLD = Number(options.instanceWallThreshold || 120);

    const wallMaterial = options.wallMaterial || new THREE.MeshStandardMaterial({ color: 0xffffff });
    const floorMaterial = options.floorMaterial || new THREE.MeshStandardMaterial({ color: 0x808080, roughness: 0.95 });
    const roofMaterial = options.roofMaterial || new THREE.MeshStandardMaterial({ color: 0x505050, roughness: 0.9 });
    const doorMaterial = options.doorMaterial || new THREE.MeshStandardMaterial({ color: 0x5f3b1f });
    const windowMaterial = options.windowMaterial || new THREE.MeshStandardMaterial({ color: 0x88ccff, transparent: true, opacity: 0.45 });

    if (!normalizedData || !normalizedData.floors) return buildingGroup;

    normalizedData.floors.forEach((floor, idx) => {
        const floorGroup = new THREE.Group();
        const yOffset = idx * FLOOR_HEIGHT;
        const boundary = detectFloorBoundary(floor);
        const floorSlab = createSlab(boundary, FLOOR_THICKNESS, floorMaterial, yOffset);
        if (floorSlab) floorGroup.add(floorSlab);

        const wallDescriptors = [];
        const seenWalls = new Set();
        (floor.rooms || []).forEach((room) => {
            const coords = room.coords || [];
            for (let i = 0; i < coords.length - 1; i++) {
                const key = canonicalWallKey(coords[i], coords[i + 1], idx);
                if (seenWalls.has(key)) continue;
                seenWalls.add(key);
                const d = buildWallDescriptor(coords[i], coords[i + 1], { floorIndex: idx, floorHeight: FLOOR_HEIGHT, levelOffset: yOffset });
                if (d) wallDescriptors.push(d);
            }
        });

        const openingDefaults = { thickness: WALL_THICKNESS, wallSnapTolerance: 1.0 };
        const doors = mapOpeningsToWalls(floor.doors || [], wallDescriptors, 'door', { ...openingDefaults, width: 0.95, height: 2.1, elevation: 0 });
        const windows = mapOpeningsToWalls(floor.windows || [], wallDescriptors, 'window', { ...openingDefaults, width: 1.2, height: 1.2, elevation: 0.9 });
        const openingsByWall = new Map();
        [...doors, ...windows].forEach((o) => {
            const arr = openingsByWall.get(o.wallId) || [];
            arr.push(o);
            openingsByWall.set(o.wallId, arr);
        });

        const wallsWithoutOpenings = wallDescriptors.filter((d) => !openingsByWall.has(d.id));
        const wallsWithOpenings = wallDescriptors.filter((d) => openingsByWall.has(d.id));

        if (wallsWithoutOpenings.length >= INSTANCE_WALL_THRESHOLD) {
            const instanced = createInstancedWalls(wallsWithoutOpenings, FLOOR_HEIGHT, WALL_THICKNESS, wallMaterial);
            if (instanced) floorGroup.add(instanced);
        } else {
            wallsWithoutOpenings.forEach((w) => floorGroup.add(createWallMesh(w, [], FLOOR_HEIGHT, WALL_THICKNESS, wallMaterial)));
        }

        wallsWithOpenings.forEach((w) => {
            const wallMesh = createWallMesh(w, openingsByWall.get(w.id), FLOOR_HEIGHT, WALL_THICKNESS, wallMaterial);
            floorGroup.add(wallMesh);
        });

        doors.forEach((door) => floorGroup.add(createOpeningVisual(door, yOffset, doorMaterial)));
        windows.forEach((win) => floorGroup.add(createOpeningVisual(win, yOffset, windowMaterial)));

        if (idx === normalizedData.floors.length - 1) {
            const roof = createRoof(floor, yOffset + FLOOR_HEIGHT, ROOF_THICKNESS, roofMaterial);
            if (roof) floorGroup.add(roof);
        }

        buildingGroup.add(floorGroup);
    });

    return buildingGroup;
}

export function setupThreeScene(container, options = {}) {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(options.background || 0x0b0f19);

    const camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.1, 5000);
    camera.position.set(30, 24, 30);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 0.8));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.95);
    dirLight.position.set(30, 60, 20);
    scene.add(dirLight);

    const grid = new THREE.GridHelper(200, 80, 0x446688, 0x1c2a3a);
    grid.position.y = -0.001;
    scene.add(grid);

    return { scene, camera, renderer };
}

export function exportBuildingAsGLTF(rootObject, { binary = false, fileName = null } = {}) {
    return new Promise((resolve, reject) => {
        const exporter = new GLTFExporter();
        exporter.parse(
            rootObject,
            (result) => {
                const blob = binary
                    ? new Blob([result], { type: 'model/gltf-binary' })
                    : new Blob([JSON.stringify(result)], { type: 'model/gltf+json' });
                const ext = binary ? 'glb' : 'gltf';
                resolve({
                    blob,
                    fileName: fileName || `building_model.${ext}`,
                    url: URL.createObjectURL(blob),
                });
            },
            (err) => reject(err),
            { binary }
        );
    });
}
