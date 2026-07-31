import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BoxGeometry,
  CylinderGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  Scene,
} from "three";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";

globalThis.FileReader = class {
  result = null;
  onloadend = null;
  readAsArrayBuffer(blob) {
    blob.arrayBuffer().then((result) => {
      this.result = result;
      this.onloadend?.();
    });
  }
  readAsDataURL(blob) {
    blob.arrayBuffer().then((buffer) => {
      this.result = `data:${blob.type};base64,${Buffer.from(buffer).toString("base64")}`;
      this.onloadend?.();
    });
  }
};

const currentDir = dirname(fileURLToPath(import.meta.url));
const outputDir = resolve(currentDir, "../public/models/demo");
const material = (color, roughness = 0.78) =>
  new MeshStandardMaterial({ color, roughness });
const addBox = (group, size, position, color, rotationY = 0) => {
  const mesh = new Mesh(new BoxGeometry(...size), material(color));
  mesh.position.set(...position);
  mesh.rotation.y = rotationY;
  group.add(mesh);
};
const addCylinder = (group, radius, height, position, color, segments = 32) => {
  const mesh = new Mesh(
    new CylinderGeometry(radius, radius, height, segments),
    material(color),
  );
  mesh.position.set(...position);
  group.add(mesh);
};

const factories = {
  "sofa.glb": () => {
    const group = new Group();
    addBox(group, [2.2, 0.32, 0.82], [0, 0.4, 0], 0xd9c7a8);
    addBox(group, [2.0, 0.48, 0.22], [0, 0.78, -0.3], 0xcdb791);
    addBox(group, [0.22, 0.55, 0.8], [-1.0, 0.55, 0], 0xcdb791);
    addBox(group, [0.22, 0.55, 0.8], [1.0, 0.55, 0], 0xcdb791);
    return group;
  },
  "chair.glb": () => {
    const group = new Group();
    addBox(group, [0.5, 0.12, 0.5], [0, 0.48, 0], 0x78906a);
    addBox(group, [0.5, 0.55, 0.1], [0, 0.78, -0.2], 0x526a4d);
    for (const x of [-0.2, 0.2]) for (const z of [-0.2, 0.2])
      addBox(group, [0.06, 0.48, 0.06], [x, 0.24, z], 0x8d6845);
    return group;
  },
  "coffee-table.glb": () => {
    const group = new Group();
    addCylinder(group, 0.48, 0.1, [0, 0.38, 0], 0xb58a5a);
    addCylinder(group, 0.22, 0.35, [0, 0.18, 0], 0x85613e);
    return group;
  },
  "cabinet.glb": () => {
    const group = new Group();
    addBox(group, [1.5, 1.8, 0.38], [0, 0.9, 0], 0xe7ddc8);
    addBox(group, [0.03, 1.65, 0.4], [0, 0.92, 0.01], 0xb99e78);
    addBox(group, [1.38, 0.03, 0.4], [0, 0.58, 0.01], 0xb99e78);
    return group;
  },
  "lamp.glb": () => {
    const group = new Group();
    addCylinder(group, 0.24, 0.06, [0, 0.03, 0], 0x856f55);
    addCylinder(group, 0.035, 1.2, [0, 0.62, 0], 0x856f55, 16);
    addCylinder(group, 0.28, 0.34, [0, 1.27, 0], 0xf3dfae);
    return group;
  },
  "rug.glb": () => {
    const group = new Group();
    addBox(group, [2.0, 0.025, 2.8], [0, 0.0125, 0], 0xb9aa8f);
    return group;
  },
  "bed.glb": () => {
    const group = new Group();
    addBox(group, [1.8, 0.32, 2.0], [0, 0.28, 0], 0xdbc9aa);
    addBox(group, [1.82, 0.85, 0.16], [0, 0.62, -0.92], 0xcab18b);
    addBox(group, [0.72, 0.1, 0.42], [-0.42, 0.48, -0.55], 0xf2eadc);
    addBox(group, [0.72, 0.1, 0.42], [0.42, 0.48, -0.55], 0xf2eadc);
    return group;
  },
  "desk.glb": () => {
    const group = new Group();
    addBox(group, [1.4, 0.08, 0.7], [0, 0.72, 0], 0xb99363);
    addBox(group, [0.08, 0.7, 0.6], [-0.58, 0.35, 0], 0x6c755e);
    addBox(group, [0.08, 0.7, 0.6], [0.58, 0.35, 0], 0x6c755e);
    return group;
  },
  "dining-table.glb": () => {
    const group = new Group();
    addCylinder(group, 0.65, 0.08, [0, 0.72, 0], 0xb59162);
    addCylinder(group, 0.16, 0.7, [0, 0.35, 0], 0x66594b, 24);
    addCylinder(group, 0.35, 0.06, [0, 0.03, 0], 0x66594b);
    return group;
  },
};

await mkdir(outputDir, { recursive: true });
const exporter = new GLTFExporter();
for (const [filename, factory] of Object.entries(factories)) {
  const scene = new Scene();
  scene.add(factory());
  const glb = await exporter.parseAsync(scene, {
    binary: true,
    onlyVisible: true,
  });
  await writeFile(resolve(outputDir, filename), Buffer.from(glb));
}
console.info(`Generated ${Object.keys(factories).length} demo GLB models in ${outputDir}`);
