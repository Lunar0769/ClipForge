import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useReducedMotion } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { Vector2, type ShaderMaterial } from "three";
import { StaticGradient } from "./StaticGradient";

const vertexShader = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform vec2 uRes;
  varying vec2 vUv;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
  }
  float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.0; a *= 0.5; }
    return v;
  }
  void main() {
    vec2 uv = vUv;
    uv.x *= uRes.x / max(uRes.y, 1.0);
    float t = uTime * 0.05;
    float n = fbm(uv * 2.0 + vec2(t, -t));
    float n2 = fbm(uv * 3.0 - vec2(t * 1.3, t * 0.7) + n);
    vec3 ink = vec3(0.027, 0.024, 0.051);
    vec3 violet = vec3(0.545, 0.361, 0.965);
    vec3 cyan = vec3(0.133, 0.827, 0.933);
    vec3 col = mix(ink, violet, smoothstep(0.45, 0.9, n2) * 0.55);
    col = mix(col, cyan, smoothstep(0.6, 1.0, n) * 0.35);
    col *= smoothstep(1.2, 0.2, length(vUv - 0.5) * 1.6);
    gl_FragColor = vec4(col, 1.0);
  }
`;

function NebulaPlane() {
  const material = useRef<ShaderMaterial>(null);
  const size = useThree((s) => s.size);
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uRes: { value: new Vector2(1, 1) } }), []);
  useFrame((_, delta) => {
    if (!material.current) return;
    material.current.uniforms.uTime.value += delta;
    material.current.uniforms.uRes.value.set(size.width, size.height);
  });
  return (
    <mesh>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial ref={material} vertexShader={vertexShader} fragmentShader={fragmentShader} uniforms={uniforms} depthWrite={false} />
    </mesh>
  );
}

let webglSupport: boolean | null = null;

function canUseWebGL(): boolean {
  if (webglSupport !== null) return webglSupport;
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    webglSupport = !!gl;
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
  } catch {
    webglSupport = false;
  }
  return webglSupport;
}

export default function ShaderBackground() {
  const reduced = useReducedMotion();
  const [supported] = useState(canUseWebGL);
  if (reduced || !supported) return <StaticGradient />;
  return (
    <div aria-hidden="true" className="absolute inset-0 opacity-90 [html[data-theme=light]_&]:opacity-25">
      <Canvas dpr={[1, 1.5]} gl={{ antialias: false, powerPreference: "low-power" }}>
        <NebulaPlane />
      </Canvas>
    </div>
  );
}
