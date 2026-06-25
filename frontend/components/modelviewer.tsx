"use client";

import { Suspense, useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stage, useGLTF, Grid } from "@react-three/drei";

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

/** 3D 模型查看弹窗。url 指向带贴图的 GLB。 */
export function ModelViewer({ url, onClose }: { url: string; onClose: () => void }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
    // 预加载, 失败也不阻塞
    try { useGLTF.preload(url); } catch { /* noop */ }
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [url, onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-[90vw] h-[85vh] max-w-5xl rounded-xl overflow-hidden border border-slate-700 bg-slate-950"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-4 py-2 bg-slate-900/80">
          <span className="text-sm font-medium text-slate-200">3D 效果预览</span>
          <div className="flex items-center gap-3">
            <a
              href={url}
              download
              className="text-xs text-sky-400 hover:text-sky-300"
              onClick={(e) => e.stopPropagation()}
            >
              下载 GLB
            </a>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-200 text-lg leading-none"
            >
              ✕
            </button>
          </div>
        </div>

        {mounted && (
          <Canvas camera={{ position: [0, 0, 3], fov: 45 }} dpr={[1, 2]}>
            <color attach="background" args={["#0a0e1a"]} />
            <Suspense fallback={null}>
              <Stage environment="city" intensity={0.5} adjustCamera={1.2}>
                <Model url={url} />
              </Stage>
            </Suspense>
            <Grid
              infiniteGrid
              cellSize={0.5}
              sectionSize={2}
              fadeDistance={25}
              fadeStrength={1}
              cellColor="#1e293b"
              sectionColor="#334155"
            />
            <OrbitControls makeDefault enableDamping dampingFactor={0.1} />
          </Canvas>
        )}

        <div className="absolute bottom-2 left-0 right-0 text-center text-xs text-slate-500">
          鼠标拖动旋转 · 滚轮缩放 · 右键平移 · Esc 关闭
        </div>
      </div>
    </div>
  );
}
