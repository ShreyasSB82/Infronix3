/**
 * antiGravityGenerator.js  v1.0
 * =============================
 * Generates BIM Anti-Gravity Core geometry as three-cad-viewer Shapes nodes.
 *
 * Components produced (per the INFRONIX_BIM_IMPLEMENTATION spec):
 *   /AGCore/GlassEnvelope       glass curtain wall (transparent blue)
 *   /AGCore/GravityVoid         semi-transparent levitation field volume
 *   /AGCore/SCShaft             superconducting YBCO shaft (gray cylinder)
 *   /AGCore/Floor{N}/Ring       levitation torus ring (amber/gold, per floor)
 *   /AGCore/CryoHelix           LN₂ cryo-cooling spiral tube (blue)
 *   /AGCore/MEP/Water           BWSSB water supply line (blue)
 *   /AGCore/MEP/Sewage          UGD sewage line (brown)
 *   /AGCore/MEP/Drainage        SWD stormwater drainage (teal)
 */

// ── Geometry helpers (no Three.js — vanilla math only) ───────────────────────

/**
 * Generate a flat array of [x, z] points for a circle in the XZ plane.
 */
function circleRing(cx, cz, radius, segments = 32) {
  const pts = [];
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    pts.push([cx + radius * Math.cos(a), cz + radius * Math.sin(a)]);
  }
  return pts;
}

/**
 * Build a rectangle ring [x, z] from centre + half-extents.
 */
function rectRing(cx, cz, hw, hd) {
  return [
    [cx - hw, cz - hd],
    [cx + hw, cz - hd],
    [cx + hw, cz + hd],
    [cx - hw, cz + hd],
  ];
}

/**
 * Triangulate an arbitrarily sized convex/concave ring using earcut.
 * Returns { ring, tris }.
 */
function tri(ring) {
  // In ES module scope, `typeof undeclaredVar` works fine, but
  // direct `earcut` access throws ReferenceError — use window only.
  const earc = (typeof window !== 'undefined' && window.earcut) ? window.earcut : null;

  // Validate ring is a proper array of [x, z] pairs
  if (!Array.isArray(ring) || ring.length < 3) {
    return { ring: ring || [], tris: [] };
  }

  if (!earc) {
    // fan fallback (works for convex polygons)
    const tris = [];
    for (let i = 1; i < ring.length - 1; i++) tris.push(0, i, i + 1);
    return { ring, tris };
  }
  const flat = [];
  for (let i = 0; i < ring.length; i++) {
    flat.push(ring[i][0], ring[i][1]);
  }
  return { ring, tris: earc(flat, null, 2) };
}

/**
 * Build a complete extruded mesh (vertices/normals/triangles/edges) from a 2D ring.
 * Matches the tessellateExtrusion format expected by three-cad-viewer.
 */
function extrude(ring2d, height, yBase) {
  const { ring: pts, tris: tris2d } = tri(ring2d);
  const N = pts.length;
  if (N < 3 || tris2d.length < 3) return null;

  const vertices = [], normals = [], triangles = [];

  // Bottom ring (y = yBase)
  for (const [x, z] of pts) { vertices.push(x, yBase, z);          normals.push(0, -1, 0); }
  // Top ring (y = yBase + height)
  for (const [x, z] of pts) { vertices.push(x, yBase + height, z); normals.push(0,  1, 0); }

  const botCount = tris2d.length / 3;
  // Bottom cap (reversed winding → face down)
  for (let i = 0; i < tris2d.length; i += 3) triangles.push(tris2d[i+2], tris2d[i+1], tris2d[i]);
  // Top cap
  for (let i = 0; i < tris2d.length; i += 3) triangles.push(N+tris2d[i], N+tris2d[i+1], N+tris2d[i+2]);

  // Side quads
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

  // Edge outline
  const edges = [];
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N;
    const [x0,z0] = pts[i], [x1,z1] = pts[j];
    edges.push(x0, yBase, z0, x1, yBase, z1);
    edges.push(x0, yBase+height, z0, x1, yBase+height, z1);
    edges.push(x0, yBase, z0, x0, yBase+height, z0);
  }
  const numEdges = 3 * N;

  const obj_vertices = [];
  for (const [x,z] of pts) obj_vertices.push(x, yBase, z);
  for (const [x,z] of pts) obj_vertices.push(x, yBase+height, z);

  return {
    vertices, normals, triangles,
    triangles_per_face: [botCount, botCount, ...sideCounts],
    face_types:  new Array(2 + N).fill(0),
    edges, edge_types: new Array(numEdges).fill(0),
    segments_per_edge: new Array(numEdges).fill(1),
    obj_vertices,
  };
}

// ── Shapes leaf / group builders ─────────────────────────────────────────────

function leaf(id, name, ring2d, height, yBase, color, alpha = 1.0, renderback = false) {
  const shape = extrude(ring2d, height, yBase);
  if (!shape) return null;
  return {
    version: 3, id, name,
    type: 'shapes', subtype: 'solid',
    state: [1, 1],
    color, alpha, renderback,
    texture: null, accuracy: null, bb: null,
    loc: [[0,0,0],[0,0,0,1]],
    shape,
  };
}

function group(id, name, parts) {
  return { version: 3, id, name, loc: [[0,0,0],[0,0,0,1]], parts };
}

// ── Bounding box ─────────────────────────────────────────────────────────────

function emptyBB() { return { xmin:1e9, xmax:-1e9, ymin:1e9, ymax:-1e9, zmin:1e9, zmax:-1e9 }; }
function expandBB(bb, x, y, z) {
  if (x<bb.xmin) bb.xmin=x; if (x>bb.xmax) bb.xmax=x;
  if (y<bb.ymin) bb.ymin=y; if (y>bb.ymax) bb.ymax=y;
  if (z<bb.zmin) bb.zmin=z; if (z>bb.zmax) bb.zmax=z;
}
function ringBB(bb, ring, y0, y1) {
  for (const [x,z] of ring) { expandBB(bb,x,y0,z); expandBB(bb,x,y1,z); }
}

// ── Main generator ────────────────────────────────────────────────────────────

/**
 * generateAGCore(config)
 *
 * config:
 *   floors        — number of floors (default 3)
 *   floorHeight   — metres per floor (default 3.2)
 *   buildingWidth — X extent of building footprint (default 20)
 *   buildingDepth — Z extent of building footprint (default 15)
 *   cx, cz        — centre of building in local space (default 0,0)
 *
 * Returns a Shapes group node: { version, id, name, bb, parts }
 */
export function generateAGCore(config = {}) {
  const floors      = config.floors      ?? 3;
  const FH          = config.floorHeight ?? 3.2;
  const totalH      = floors * FH;
  const BW          = config.buildingWidth  ?? 20;
  const BD          = config.buildingDepth  ?? 15;
  const cx          = config.cx ?? 0;
  const cz          = config.cz ?? 0;

  const SHAFT_R     = 0.4;
  const RING_R      = Math.min(6.0, Math.min(BW, BD) * 0.2);
  const SLAB_H_FRAC = 0.15; // shaft collar per floor

  const bb   = emptyBB();
  const parts = [];

  // ── 1. Glass Curtain Wall Envelope [MOVED TO cadViewerBridge FOR REAL BOUNDARY]
  // const envHW = BW / 2 + 0.25, envHD = BD / 2 + 0.25;
  // const envRing = rectRing(cx, cz, envHW, envHD);
  // const envLeaf = leaf('/AGCore/GlassEnvelope', '🪟 Black Glass Cover',
  //   envRing, totalH, 0, '#334155', 0.20, true);
  // if (envLeaf) { parts.push(envLeaf); ringBB(bb, envRing, 0, totalH); }

  // ── 2. Gravity Void Volume ─────────────────────────────────────────────────
  const vHW = BW / 2 - 1.0, vHD = BD / 2 - 1.0;
  const voidRing = rectRing(cx, cz, vHW, vHD);
  const voidLeaf = leaf('/AGCore/GravityVoid', '🔮 Gravity Field 12.5T',
    voidRing, totalH, 0, '#7c4dff', 0.08, true);
  if (voidLeaf) { parts.push(voidLeaf); ringBB(bb, voidRing, 0, totalH); }

  // ── 3. Superconducting Shaft (YBCO) ───────────────────────────────────────
  const shaftRing = circleRing(cx, cz, SHAFT_R, 32);
  const shaftLeaf = leaf('/AGCore/SCShaft', '⚙ SC-Shaft YBCO 77K',
    shaftRing, totalH, 0, '#8b8b8b', 1.0);
  if (shaftLeaf) { parts.push(shaftLeaf); ringBB(bb, shaftRing, 0, totalH); }

  // ── 4. Levitation Rings (one per floor) ───────────────────────────────────
  const ringParts = [];
  for (let i = 0; i < floors; i++) {
    const elev     = i * FH + FH * 0.5;
    const outerPts = circleRing(cx, cz, RING_R, 48);
    const innerR   = RING_R - 0.25;

    // Build ring as a thick annular extrusion: extrude the outer ring, then
    // subtract inner by rendering both (viewer handles overlap via alpha).
    const outerLeaf = leaf(
      `/AGCore/Floor${i+1}/Ring`,
      `⚡ Ring F${i+1} 240kN`,
      outerPts, SLAB_H_FRAC, elev - SLAB_H_FRAC / 2,
      '#f59e0b', 0.92
    );
    const innerRing = circleRing(cx, cz, innerR, 48);
    const innerLeaf = leaf(
      `/AGCore/Floor${i+1}/RingInner`,
      `Ring F${i+1} void`,
      innerRing, SLAB_H_FRAC + 0.02, elev - SLAB_H_FRAC / 2 - 0.01,
      '#080c18', 1.0
    );

    if (outerLeaf) { ringParts.push(outerLeaf); ringBB(bb, outerPts, elev, elev + SLAB_H_FRAC); }
    if (innerLeaf)   ringParts.push(innerLeaf);
  }
  if (ringParts.length) parts.push(group('/AGCore/Rings', '🔆 Levitation Rings', ringParts));

  // ── 5. Cryo-Cooling Helix ─────────────────────────────────────────────────
  // Approximate helix as many small flat disc segments along a spiral path
  const cryoParts = [];
  const CRYO_R   = SHAFT_R + 0.65;
  const TURNS    = floors * 2;
  const STEPS    = TURNS * 16;
  const DISC_R   = 0.06;
  const DISC_H   = 0.04;

  for (let s = 0; s < STEPS; s++) {
    const a0 = (s       / STEPS) * TURNS * Math.PI * 2;
    const a1 = ((s + 1) / STEPS) * TURNS * Math.PI * 2;
    const hx = cx + CRYO_R * Math.cos((a0+a1)/2);
    const hz = cz + CRYO_R * Math.sin((a0+a1)/2);
    const hy = (s / STEPS) * totalH;

    const discRing = circleRing(hx, hz, DISC_R, 8);
    const discLeaf = leaf(
      `/AGCore/Cryo/${s}`,
      `Cryo ${s}`,
      discRing, DISC_H, hy,
      '#1565c0', 0.85
    );
    if (discLeaf) { cryoParts.push(discLeaf); }
  }
  if (cryoParts.length) {
    parts.push(group('/AGCore/CryoHelix', '❄ LN₂ Cryo Loop', cryoParts));
  }

  // ── 6. Underground MEP Connections ────────────────────────────────────────
  const mepParts = [];
  const PIPE_R   = 0.08;
  const PIPE_H   = 8.0;
  const southEdge = cz - BD / 2;
  const eastEdge  = cx + BW / 2;
  const northEdge = cz + BD / 2;

  // Water supply — BWSSB, vertical stub from -1m below grade to building face
  const waterRing = circleRing(cx - 1.5, southEdge - 4.0, PIPE_R, 12);
  const waterLeaf = leaf('/AGCore/MEP/Water', '💧 BWSSB Water DN25',
    waterRing, PIPE_H, -1.0, '#1565c0', 0.85);
  if (waterLeaf) { mepParts.push(waterLeaf); }

  // Sewage — UGD, horizontal stub from east edge
  const sewerRing = circleRing(eastEdge + 3.0, cz + 1.5, PIPE_R, 12);
  const sewerLeaf = leaf('/AGCore/MEP/Sewage', '🟤 UGD Sewage DN150',
    sewerRing, PIPE_H, -1.5, '#6d4c41', 0.85);
  if (sewerLeaf) { mepParts.push(sewerLeaf); }

  // Stormwater drainage — SWD, vertical stub from north edge
  const swdRing = circleRing(cx + 2.0, northEdge + 3.0, PIPE_R * 1.5, 12);
  const swdLeaf = leaf('/AGCore/MEP/Drainage', '🌊 SWD Drainage DN100',
    swdRing, PIPE_H, -0.6, '#00796b', 0.85);
  if (swdLeaf) { mepParts.push(swdLeaf); }

  if (mepParts.length) {
    parts.push(group('/AGCore/MEP', '🔧 MEP Infrastructure', mepParts));
  }

  // ── Fix bounding box ──────────────────────────────────────────────────────
  if (!isFinite(bb.xmin)) {
    bb.xmin = cx - BW/2; bb.xmax = cx + BW/2;
    bb.ymin = 0;         bb.ymax = totalH;
    bb.zmin = cz - BD/2; bb.zmax = cz + BD/2;
  }

  return {
    version: 3,
    id:   '/AGCore',
    name: '🔮 Anti-Gravity BIM Core',
    loc:  [[0,0,0],[0,0,0,1]],
    normal_len: 0,
    bb,
    parts,
  };
}

/**
 * buildAGConfig(sitePlan, interior)
 * Derive AG core config from the existing layout data.
 */
export function buildAGConfig(sitePlan, interior) {
  const floors = interior?.floors?.length || sitePlan?.num_floors || 3;

  // Try to derive building footprint size from site zones
  let BW = 20, BD = 15;
  const features = sitePlan?.zones?.features || [];
  for (const f of features) {
    if ((f.properties?.zone || '').toLowerCase() !== 'building') continue;
    const coords = f.geometry?.coordinates?.[0] || [];
    if (coords.length < 3) continue;
    const xs = coords.map(c => c[0]);
    const ys = coords.map(c => c[1]);
    // Convert coordinate range: rough approximation in metres
    const dlon = Math.max(...xs) - Math.min(...xs);
    const dlat = Math.max(...ys) - Math.min(...ys);
    BW = Math.max(5, dlon * 111320 * Math.cos(Math.min(...ys) * Math.PI / 180));
    BD = Math.max(5, dlat * 111320);
    break;
  }

  return { floors, floorHeight: 3.2, buildingWidth: BW, buildingDepth: BD, cx: 0, cz: 0 };
}
