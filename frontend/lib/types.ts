export type ProbeItem = {
  ok: boolean;
  reason?: string | null;
  resolved?: string;
  status?: number;
};

export type ProbeResult = {
  blender: ProbeItem;
  comfyui: ProbeItem;
  comfyui_workflow: ProbeItem;
  python: ProbeItem;
};

export type AppConfig = {
  blender_executable?: string | null;
  comfyui_base_url: string;
  comfyui_workflow?: string | null;
  python_executable?: string | null;
  output_dir?: string | null;
  temp_dir?: string | null;
};

export type StageState = {
  name: "render" | "inpaint" | "reconstruct";
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  outputs: string[];
};

export type ViewState = {
  cam: string;
  render_path?: string | null;
  inpaint_path?: string | null;       // 差分遮罩 (给 reconstruct 用)
  ai_wear_path?: string | null;        // AI 生成的磨损图 (预览用)
  bg_removed_path?: string | null;     // 选中的去背景图 (作为 inpaint 输入)
  bg_candidates?: Record<string, string>; // {inspyrenet|bria|sam: rel_path}
  upscaled_path?: string | null;       // SeedVR2 放大后的高清图
  upscale_enabled?: boolean;           // 是否启用放大图作为 inpaint 输入
  inpaint_status: "pending" | "running" | "completed" | "failed" | "skipped";
  prompt_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
};

export type TaskStatus =
  | "pending"
  | "queued"
  | "running"
  | "rendering"
  | "inpainting"
  | "awaiting_confirm"
  | "reconstructing"
  | "completed"
  | "failed"
  | "cancelled";

export type UploadedFile = {
  name: string;
  role: string;
  size: number;
  relative_path: string;
};

export type TaskParams = {
  name?: string | null;
  resolution: number;
  samples: number;
  cam_distance: number;
  enable_inpaint: boolean;
  confirm_before_reconstruct: boolean;
  wear_intensity: number;
  wear_preset: string;
  material_type: string;
  wear_model: string;
  target_object: string;
  tex_size: number;
  inpaint_iters: number;
  seam_dilate: number;
  mask_denoise: string;
  facing_min: number;
  occlusion_rel: number;
  save_debug: boolean;
  final_name: string;
  output_basename?: string | null;
  workflow_override?: string | null;
  extra?: Record<string, unknown>;
};

export type Task = {
  id: string;
  name?: string | null;
  status: TaskStatus;
  params: TaskParams;
  inputs: UploadedFile[];
  outputs: { renders: string[]; inpaint: string[]; textures: string[]; debug: string[]; glb: string[] };
  views: ViewState[];
  stages: StageState[];
  error?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};
