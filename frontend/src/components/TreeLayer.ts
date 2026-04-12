/**
 * Renders millions of 3D trees using raw WebGL instanced rendering.
 * Each tree = brown cylinder (trunk) + green sphere-ish (canopy).
 * Uses MapLibre's CustomLayerInterface with manual WebGL — no Three.js dependency.
 */
import maplibregl from 'maplibre-gl';

interface TreeData {
  p: [number, number]; // [lng, lat]
  h: number;           // height in meters
}

const VERT_TRUNK = `
  attribute vec3 aPos;       // unit cylinder vertex
  attribute vec3 aInstancePos; // [mercX, mercY, mercZ]
  attribute vec2 aInstanceSize; // [radius, height] in mercator units
  uniform mat4 uMatrix;
  varying float vShade;
  void main() {
    vec3 pos = aPos;
    pos.xy *= aInstanceSize.x;
    pos.z *= aInstanceSize.y;
    pos += aInstancePos;
    gl_Position = uMatrix * vec4(pos, 1.0);
    vShade = 0.6 + 0.4 * aPos.z; // simple shading
  }
`;

const FRAG_TRUNK = `
  precision mediump float;
  varying float vShade;
  uniform vec3 uColor;
  void main() {
    gl_FragColor = vec4(uColor * vShade, 1.0);
  }
`;

function createCylinder(segments: number): { verts: Float32Array; indices: Uint16Array } {
  const verts: number[] = [];
  const idx: number[] = [];
  // Bottom center
  verts.push(0, 0, 0);
  // Bottom ring
  for (let i = 0; i < segments; i++) {
    const a = (2 * Math.PI * i) / segments;
    verts.push(Math.cos(a), Math.sin(a), 0);
  }
  // Top center
  verts.push(0, 0, 1);
  // Top ring
  for (let i = 0; i < segments; i++) {
    const a = (2 * Math.PI * i) / segments;
    verts.push(Math.cos(a), Math.sin(a), 1);
  }
  // Bottom cap
  for (let i = 0; i < segments; i++) {
    idx.push(0, 1 + i, 1 + ((i + 1) % segments));
  }
  // Top cap
  const topCenter = segments + 1;
  for (let i = 0; i < segments; i++) {
    idx.push(topCenter, topCenter + 1 + ((i + 1) % segments), topCenter + 1 + i);
  }
  // Side
  for (let i = 0; i < segments; i++) {
    const b0 = 1 + i, b1 = 1 + ((i + 1) % segments);
    const t0 = topCenter + 1 + i, t1 = topCenter + 1 + ((i + 1) % segments);
    idx.push(b0, b1, t1);
    idx.push(b0, t1, t0);
  }
  return { verts: new Float32Array(verts), indices: new Uint16Array(idx) };
}

function compileShader(gl: WebGLRenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    console.error('Shader error:', gl.getShaderInfoLog(s));
  }
  return s;
}

export function createTreeLayer(trees: TreeData[]): maplibregl.CustomLayerInterface {
  let program: WebGLProgram;
  let vertBuf: WebGLBuffer;
  let idxBuf: WebGLBuffer;
  let instancePosBuf: WebGLBuffer;
  let instanceSizeBuf: WebGLBuffer;
  let numIndices: number;
  let numInstances: number;

  // Canopy
  let canopyProgram: WebGLProgram;
  let canopyVertBuf: WebGLBuffer;
  let canopyIdxBuf: WebGLBuffer;
  let canopyPosBuf: WebGLBuffer;
  let canopySizeBuf: WebGLBuffer;
  let canopyColorBuf: WebGLBuffer;
  let canopyNumIdx: number;

  const EXAG = 1.5;

  const VERT_CANOPY = `
    attribute vec3 aPos;
    attribute vec3 aInstancePos;
    attribute vec2 aInstanceSize;
    attribute vec3 aColor;
    uniform mat4 uMatrix;
    varying float vShade;
    varying vec3 vColor;
    void main() {
      vec3 pos = aPos;
      pos.xy *= aInstanceSize.x;
      pos.z *= aInstanceSize.y;
      pos += aInstancePos;
      gl_Position = uMatrix * vec4(pos, 1.0);
      vShade = 0.5 + 0.5 * aPos.z;
      vColor = aColor;
    }
  `;

  const FRAG_CANOPY = `
    precision mediump float;
    varying float vShade;
    varying vec3 vColor;
    void main() {
      gl_FragColor = vec4(vColor * vShade, 0.85);
    }
  `;

  return {
    id: 'trees-3d',
    type: 'custom' as const,
    renderingMode: '3d',

    onAdd(_map: maplibregl.Map, gl: WebGLRenderingContext) {
      const ext = gl.getExtension('ANGLE_instanced_arrays');
      if (!ext) { console.error('ANGLE_instanced_arrays not supported'); return; }

      numInstances = trees.length;
      const cyl = createCylinder(6);
      numIndices = cyl.indices.length;

      // --- Build instance data ---
      const posData = new Float32Array(numInstances * 3);
      const trunkSizeData = new Float32Array(numInstances * 2);
      const canopyPosData = new Float32Array(numInstances * 3);
      const canopySizeData = new Float32Array(numInstances * 2);
      const colorData = new Float32Array(numInstances * 3);

      const greens = [
        [0.18, 0.49, 0.20], [0.22, 0.56, 0.24], [0.26, 0.63, 0.28],
        [0.11, 0.37, 0.13], [0.20, 0.41, 0.12], [0.30, 0.69, 0.31],
      ];

      for (let i = 0; i < numInstances; i++) {
        const t = trees[i];
        const mc = maplibregl.MercatorCoordinate.fromLngLat(t.p, 0);
        const s = mc.meterInMercatorCoordinateUnits();
        const h = t.h * EXAG;

        // Trunk
        const trunkR = Math.max(0.15, t.h * 0.04) * s;
        const trunkH = h * 0.3 * s;
        posData[i * 3] = mc.x;
        posData[i * 3 + 1] = mc.y;
        posData[i * 3 + 2] = mc.z!;
        trunkSizeData[i * 2] = trunkR;
        trunkSizeData[i * 2 + 1] = trunkH;

        // Canopy (elevated by trunk height)
        const canopyR = Math.max(1.5, t.h * 0.35) * s;
        const canopyH = h * 0.7 * s;
        canopyPosData[i * 3] = mc.x;
        canopyPosData[i * 3 + 1] = mc.y;
        canopyPosData[i * 3 + 2] = mc.z! + trunkH;
        canopySizeData[i * 2] = canopyR;
        canopySizeData[i * 2 + 1] = canopyH;

        const g = greens[i % greens.length];
        colorData[i * 3] = g[0];
        colorData[i * 3 + 1] = g[1];
        colorData[i * 3 + 2] = g[2];
      }

      // --- Trunk program ---
      const vs = compileShader(gl, gl.VERTEX_SHADER, VERT_TRUNK);
      const fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAG_TRUNK);
      program = gl.createProgram()!;
      gl.attachShader(program, vs);
      gl.attachShader(program, fs);
      gl.linkProgram(program);

      vertBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, vertBuf);
      gl.bufferData(gl.ARRAY_BUFFER, cyl.verts, gl.STATIC_DRAW);

      idxBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idxBuf);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, cyl.indices, gl.STATIC_DRAW);

      instancePosBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, instancePosBuf);
      gl.bufferData(gl.ARRAY_BUFFER, posData, gl.STATIC_DRAW);

      instanceSizeBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, instanceSizeBuf);
      gl.bufferData(gl.ARRAY_BUFFER, trunkSizeData, gl.STATIC_DRAW);

      // --- Canopy program ---
      const cvs = compileShader(gl, gl.VERTEX_SHADER, VERT_CANOPY);
      const cfs = compileShader(gl, gl.FRAGMENT_SHADER, FRAG_CANOPY);
      canopyProgram = gl.createProgram()!;
      gl.attachShader(canopyProgram, cvs);
      gl.attachShader(canopyProgram, cfs);
      gl.linkProgram(canopyProgram);

      canopyVertBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, canopyVertBuf);
      gl.bufferData(gl.ARRAY_BUFFER, cyl.verts, gl.STATIC_DRAW);

      canopyIdxBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, canopyIdxBuf);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, cyl.indices, gl.STATIC_DRAW);
      canopyNumIdx = cyl.indices.length;

      canopyPosBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, canopyPosBuf);
      gl.bufferData(gl.ARRAY_BUFFER, canopyPosData, gl.STATIC_DRAW);

      canopySizeBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, canopySizeBuf);
      gl.bufferData(gl.ARRAY_BUFFER, canopySizeData, gl.STATIC_DRAW);

      canopyColorBuf = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, canopyColorBuf);
      gl.bufferData(gl.ARRAY_BUFFER, colorData, gl.STATIC_DRAW);

      console.log(`TreeLayer: ${numInstances} trees, ${(posData.byteLength + trunkSizeData.byteLength + canopyPosData.byteLength + canopySizeData.byteLength + colorData.byteLength) / 1e6}MB GPU`);
    },

    render(gl: WebGLRenderingContext, args: any) {
      const ext = gl.getExtension('ANGLE_instanced_arrays')!;
      const matrix = args.defaultProjectionData.mainMatrix;

      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      // --- Draw trunks ---
      gl.useProgram(program);
      gl.uniformMatrix4fv(gl.getUniformLocation(program, 'uMatrix'), false, matrix);
      gl.uniform3f(gl.getUniformLocation(program, 'uColor'), 0.36, 0.25, 0.22);

      const aPosLoc = gl.getAttribLocation(program, 'aPos');
      const aInstPosLoc = gl.getAttribLocation(program, 'aInstancePos');
      const aInstSizeLoc = gl.getAttribLocation(program, 'aInstanceSize');

      gl.bindBuffer(gl.ARRAY_BUFFER, vertBuf);
      gl.enableVertexAttribArray(aPosLoc);
      gl.vertexAttribPointer(aPosLoc, 3, gl.FLOAT, false, 0, 0);
      ext.vertexAttribDivisorANGLE(aPosLoc, 0);

      gl.bindBuffer(gl.ARRAY_BUFFER, instancePosBuf);
      gl.enableVertexAttribArray(aInstPosLoc);
      gl.vertexAttribPointer(aInstPosLoc, 3, gl.FLOAT, false, 0, 0);
      ext.vertexAttribDivisorANGLE(aInstPosLoc, 1);

      gl.bindBuffer(gl.ARRAY_BUFFER, instanceSizeBuf);
      gl.enableVertexAttribArray(aInstSizeLoc);
      gl.vertexAttribPointer(aInstSizeLoc, 2, gl.FLOAT, false, 0, 0);
      ext.vertexAttribDivisorANGLE(aInstSizeLoc, 1);

      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idxBuf);
      ext.drawElementsInstancedANGLE(gl.TRIANGLES, numIndices, gl.UNSIGNED_SHORT, 0, numInstances);

      // --- Draw canopies ---
      gl.useProgram(canopyProgram);
      gl.uniformMatrix4fv(gl.getUniformLocation(canopyProgram, 'uMatrix'), false, matrix);

      const caPosLoc = gl.getAttribLocation(canopyProgram, 'aPos');
      const caInstPosLoc = gl.getAttribLocation(canopyProgram, 'aInstancePos');
      const caInstSizeLoc = gl.getAttribLocation(canopyProgram, 'aInstanceSize');
      const caColorLoc = gl.getAttribLocation(canopyProgram, 'aColor');

      gl.bindBuffer(gl.ARRAY_BUFFER, canopyVertBuf);
      gl.enableVertexAttribArray(caPosLoc);
      gl.vertexAttribPointer(caPosLoc, 3, gl.FLOAT, false, 0, 0);
      ext.vertexAttribDivisorANGLE(caPosLoc, 0);

      gl.bindBuffer(gl.ARRAY_BUFFER, canopyPosBuf);
      gl.enableVertexAttribArray(caInstPosLoc);
      gl.vertexAttribPointer(caInstPosLoc, 3, gl.FLOAT, false, 0, 0);
      ext.vertexAttribDivisorANGLE(caInstPosLoc, 1);

      gl.bindBuffer(gl.ARRAY_BUFFER, canopySizeBuf);
      gl.enableVertexAttribArray(caInstSizeLoc);
      gl.vertexAttribPointer(caInstSizeLoc, 2, gl.FLOAT, false, 0, 0);
      ext.vertexAttribDivisorANGLE(caInstSizeLoc, 1);

      gl.bindBuffer(gl.ARRAY_BUFFER, canopyColorBuf);
      gl.enableVertexAttribArray(caColorLoc);
      gl.vertexAttribPointer(caColorLoc, 3, gl.FLOAT, false, 0, 0);
      ext.vertexAttribDivisorANGLE(caColorLoc, 1);

      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, canopyIdxBuf);
      ext.drawElementsInstancedANGLE(gl.TRIANGLES, canopyNumIdx, gl.UNSIGNED_SHORT, 0, numInstances);

      // Reset divisors
      ext.vertexAttribDivisorANGLE(aInstPosLoc, 0);
      ext.vertexAttribDivisorANGLE(aInstSizeLoc, 0);
      ext.vertexAttribDivisorANGLE(caInstPosLoc, 0);
      ext.vertexAttribDivisorANGLE(caInstSizeLoc, 0);
      ext.vertexAttribDivisorANGLE(caColorLoc, 0);
    },
  };
}
