/**
 * interiorMepGenerator.js
 * =======================
 * Generates Cartesian/Manhattan routed 3D MEP pipelines.
 * All plumbing runs strictly parallel to X/Z grid lines with 90-degree junctions.
 */

// ── Math & Geometry Helpers (High-Poly Vector) ──────────────────────────────

function circleRing(cx, cz, radius, segments = 16) {
  const pts = [];
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    pts.push([cx + radius * Math.cos(a), cz + radius * Math.sin(a)]);
  }
  return pts;
}

function tri(ring) {
  const earc = (typeof window !== 'undefined' && window.earcut) ? window.earcut : null;
  if (!Array.isArray(ring) || ring.length < 3) return { ring: ring||[], tris: [] };
  if (!earc) {
    const tris = [];
    for (let i = 1; i < ring.length - 1; i++) tris.push(0, i, i + 1);
    return { ring, tris };
  }
  const flat = [];
  for (let i = 0; i < ring.length; i++) flat.push(ring[i][0], ring[i][1]);
  return { ring, tris: earc(flat, null, 2) };
}

function extrude(ring2d, height, yBase) {
  const { ring: pts, tris: tris2d } = tri(ring2d);
  const N = pts.length;
  if (N < 3 || tris2d.length < 3) return null;

  const vertices = [], normals = [], triangles = [];
  for (const [x, z] of pts) { vertices.push(x, yBase, z);          normals.push(0, -1, 0); }
  for (const [x, z] of pts) { vertices.push(x, yBase + height, z); normals.push(0,  1, 0); }

  const botCount = tris2d.length / 3;
  for (let i = 0; i < tris2d.length; i += 3) triangles.push(tris2d[i+2], tris2d[i+1], tris2d[i]);
  for (let i = 0; i < tris2d.length; i += 3) triangles.push(N+tris2d[i], N+tris2d[i+1], N+tris2d[i+2]);

  let ss = 2 * N;
  const sideCounts = [];
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N;
    const [x0, z0] = pts[i], [x1, z1] = pts[j];
    const ex = x1-x0, ez = z1-z0, len = Math.sqrt(ex*ex+ez*ez)||1;
    const nx = ez/len, nz = -ex/len;
    vertices.push(x0, yBase, z0, x1, yBase, z1, x1, yBase+height, z1, x0, yBase+height, z0);
    for (let k = 0; k < 4; k++) normals.push(nx, 0, nz);
    triangles.push(ss, ss+1, ss+2, ss, ss+2, ss+3);
    ss += 4; sideCounts.push(2);
  }

  const edges = [];
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N;
    const [x0,z0] = pts[i], [x1,z1] = pts[j];
    edges.push(x0, yBase, z0, x1, yBase, z1);
    edges.push(x0, yBase+height, z0, x1, yBase+height, z1);
    edges.push(x0, yBase, z0, x0, yBase+height, z0);
  }

  const obj_vertices = [];
  for (const [x,z] of pts) { obj_vertices.push(x, yBase, z); obj_vertices.push(x, yBase+height, z); }

  return {
    vertices, normals, triangles,
    triangles_per_face: [botCount, botCount, ...sideCounts],
    face_types:  new Array(2 + N).fill(0),
    edges, edge_types: new Array(3*N).fill(1), // FormIt style crisp lines
    segments_per_edge: new Array(3*N).fill(1),
    obj_vertices,
  };
}

function leaf(id, name, ring2d, height, yBase, color) {
  const shape = extrude(ring2d, height, yBase);
  if (!shape) return null;
  return { version: 3, id, name, type: 'shapes', subtype: 'solid', state: [1, 1], color, alpha: 1.0, renderback: false, loc: [[0,0,0],[0,0,0,1]], shape };
}

// ── Layout Intelligence & Routing ───────────────────────────────────────────

function centroid(coords) {
  if (!coords || !coords.length) return [0, 0];
  let sx=0, sy=0;
  for(const p of coords) { sx+=p[0]; sy+=p[1]; }
  return [sx/coords.length, sy/coords.length];
}

function isGeo(coords) {
  return coords.length && (coords[0][0] > 70 && coords[0][0] < 100);
}

function getLocal(pt, cx, cy, is_geo) {
  if (!is_geo) return [pt[0]-cx, +(pt[1]-cy)];
  const dx = (pt[0]-cx)*111320*Math.cos(cy*Math.PI/180);
  const dy = (pt[1]-cy)*111320;
  return [dx, dy];
}

/**
 * Creates an X/Z grid-aligned horizontal rectangular pipe sweep.
 */
function manhattanPipe(ax, az, bx, bz, width, height, yBase, id, name, color, partsArray) {
  if (Math.abs(ax - bx) < 0.01 && Math.abs(az - bz) < 0.01) return;
  const hw = width / 2;
  const ring = [
    [ax - hw, az - hw],
    [bx + hw, az - hw],
    [bx + hw, bz + hw],
    [ax - hw, bz + hw],
  ];
  // Sort coordinate corners to ensure convex polygon
  const sortedRing = [
    [Math.min(ax, bx) - hw, Math.min(az, bz) - hw],
    [Math.max(ax, bx) + hw, Math.min(az, bz) - hw],
    [Math.max(ax, bx) + hw, Math.max(az, bz) + hw],
    [Math.min(ax, bx) - hw, Math.max(az, bz) + hw],
  ];
  partsArray.push(leaf(id, name, sortedRing, height, yBase, color));
}

/**
 * generateMEP(interiorLayout)
 * Generates Cartesian-routed interior architecture MEP layout.
 */
export function generateMEP(interior) {
  const floors = interior?.floors;
  if (!floors || !floors.length) return null;

  const samplePt = floors.flatMap(f => f.rooms?.map(r => r.coords?.[0]) || []).find(Boolean);
  const geographic = samplePt ? isGeo([samplePt]) : false;
  const allPts = floors.flatMap(f => [...(f.boundary || []), ...(f.rooms || []).flatMap(r => r.coords || [])]);
  const [cx, cy] = centroid(allPts);

  const FLOOR_H = 3.2;
  const PIPE_R  = 0.05; // 100mm pipe
  const parts   = [];

  // Identify core for shafts
  let coreCenter = [0, 0];
  const targetRooms = [];
  
  for (let fIdx=0; fIdx<floors.length; fIdx++) {
    const yBase = fIdx * FLOOR_H;
    const yCeiling = yBase + FLOOR_H - 0.3; // Suspended ceiling routing
    
    let wetRooms = (floors[fIdx].rooms || []).filter(r => /util|bath|wash|kitchen|core/i.test(r.type || r.name));
    if (!wetRooms.length && (floors[fIdx].rooms?.length)) wetRooms = floors[fIdx].rooms;

    wetRooms.forEach(r => {
      if (r.coords?.length) {
        const [lx, lz] = getLocal(centroid(r.coords), cx, cy, geographic);
        targetRooms.push({ fIdx, x: lx, z: lz, yCeiling });
        if (fIdx === 0) coreCenter = [lx, lz];
      }
    });
  }

  // Vertical Risers
  const totalH = floors.length * FLOOR_H + 1.0;
  
  // Vivid colors (ANSI MEP standard mappings)
  const COLOR_WATER = '#00E5FF'; // Vivid Neon Cyan
  const COLOR_SEWER = '#FF3D00'; // Safety Vermillion/Orange
  const COLOR_STORM = '#00FF00'; // Fluorescent Green
  
  const riserW = circleRing(coreCenter[0], coreCenter[1] - 0.4, PIPE_R * 1.5, 12);
  const leafW = leaf('/MEP/Riser/Water', '💧 Dom. Water Supply', riserW, totalH, -1.0, COLOR_WATER);
  if (leafW) parts.push(leafW);
  // Water Storage Tank Sub-grade
  const tankWRing = circleRing(coreCenter[0] + 0.5, coreCenter[1] - 0.4, 0.8, 24);
  const tankWLeaf = leaf('/MEP/Storage/Water', '🚰 Sub-Grade Water Tank', tankWRing, 1.8, -1.9, COLOR_WATER);
  if (tankWLeaf) parts.push(tankWLeaf);

  const riserS = circleRing(coreCenter[0], coreCenter[1] + 0.4, PIPE_R * 2.0, 12);
  const leafS = leaf('/MEP/Riser/Sewage', '🟤 Sanitary / Waste', riserS, totalH, -1.5, COLOR_SEWER);
  if (leafS) parts.push(leafS);
  // Sewer Storage Tank Sub-grade
  const tankSRing = circleRing(coreCenter[0] + 0.5, coreCenter[1] + 0.6, 1.2, 24);
  const tankSLeaf = leaf('/MEP/Storage/Sewage', '☣️ Sub-Grade Septic Tank', tankSRing, 1.6, -1.7, COLOR_STORM);
  if (tankSLeaf) parts.push(tankSLeaf);

  // Cartesian Manhattan Branches
  let branchId = 0;
  targetRooms.forEach((rm) => {
    // We route from Core -> rm.x (along X) then -> rm.z (along Z).
    const midX = rm.x;
    const coreZ = coreCenter[1];

    // Water Layout (Ceiling Level)
    const cwX = coreCenter[0], cwZ = coreCenter[1] - 0.4;
    manhattanPipe(cwX, cwZ, midX, cwZ, PIPE_R*2, PIPE_R*2, rm.yCeiling, `/MEP/Pipe/W1_${branchId}`, `W-Branch1 F${rm.fIdx}`, COLOR_WATER, parts);
    manhattanPipe(midX, cwZ, midX, rm.z, PIPE_R*2, PIPE_R*2, rm.yCeiling, `/MEP/Pipe/W2_${branchId}`, `W-Branch2 F${rm.fIdx}`, COLOR_WATER, parts);
    
    // Elbow Joint (Water)
    parts.push(leaf(`/MEP/Joint/W_${branchId}`, 'W-Elbow', circleRing(midX, cwZ, PIPE_R*1.8, 12), PIPE_R*2.1, rm.yCeiling - 0.005, COLOR_WATER));

    // Sewage Layout (Floor / Slab Level + Slope approximation logic)
    const swX = coreCenter[0], swZ = coreCenter[1] + 0.4;
    const slabLevel = rm.fIdx * FLOOR_H + 0.05; // Dropped in screed
    
    manhattanPipe(swX, swZ, midX, swZ, PIPE_R*3, PIPE_R*3, slabLevel, `/MEP/Pipe/S1_${branchId}`, `S-Branch1 F${rm.fIdx}`, COLOR_SEWER, parts);
    manhattanPipe(midX, swZ, midX, rm.z, PIPE_R*3, PIPE_R*3, slabLevel, `/MEP/Pipe/S2_${branchId}`, `S-Branch2 F${rm.fIdx}`, COLOR_SEWER, parts);
    
    // Elbow Joint (Sewage)
    parts.push(leaf(`/MEP/Joint/S_${branchId}`, 'S-Elbow', circleRing(midX, swZ, PIPE_R*2.8, 12), PIPE_R*3.1, slabLevel - 0.005, COLOR_SEWER));

    branchId++;
  });

  return {
    version: 3, id: '/BIM_MEP', name: '🔧 Cartesian MEP Plumbing',
    type: 'group', loc: [[0,0,0],[0,0,0,1]], parts,
    bb: { xmin:-20, xmax:20, ymin:0, ymax:totalH, zmin:-20, zmax:20 }
  };
}
