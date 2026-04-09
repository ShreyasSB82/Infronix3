import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';
import { createSlab, detectFloorBoundary } from './floorGenerator.js';

/**
 * Generates a flat roof from detected footprint.
 */
export function createRoof(floor, yLevel, thickness, material) {
    const boundary = detectFloorBoundary(floor);
    const roof = createSlab(boundary, thickness, material, yLevel);
    if (!roof) return null;
    roof.userData.role = 'roof';
    return roof;
}
