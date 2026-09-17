import { planShotTimeline } from "./shotTimeline";
import { readApiErrorMessage } from "./apiResponse";
import {OwnedContentDrafts} from './ownedContentDrafts';
import { ensureShotNodes } from "./shotNodes";
import { autoLayoutCanvas } from "./canvasLayout";
import {shotParameters} from './generationParameters';
import { imageSizeForRatio, VIDEO_FORMATS, VIDEO_RATIOS, VIDEO_RESOLUTIONS } from "./mediaSpecs";
import {
  planBatchGeneration,
  type BatchGenerationKind,
} from "./batchGeneration";
import { nodeDefaults } from "./nodeDefaults";
import React, {
  lazy,
  Suspense,
  useEffect,
  useState,
  useRef,
  useCallback,
} from "react";
import { createRoot } from "react-dom/client";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  type Node,
  type Edge,
  type NodeChange,
  type EdgeChange,
  type Connection,
  MarkerType,
  ReactFlowProvider,
  useReactFlow,
  useUpdateNodeInternals,
} from "@xyflow/react";
import {
  Clapperboard,
  Plus,
  Image as ImageIcon,
  Film,
  FileText,
  Layers,
  FolderOpen,
  Settings,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Play,
  Download,
  Upload,
  Clock,
  Check,
  AlertCircle,
  X,
  LoaderCircle,
  Save,
  LayoutGrid,
  Table2,
  Scissors,
  Trash2,
  Copy,
  LogOut,
  Monitor,
  Link2,
  RefreshCw,
  BookOpen,
  ArrowUpRight,
  GripVertical,
  Sparkles,
  History,
} from "lucide-react";
import "@xyflow/react/dist/style.css";
import "./style.css";
import "./timelineControls.css";
import "./filmBible/filmBible.css";
import {
  patchNode,
  invalidate,
  removeReference,
  requiresInitialStateReview,
  setInitialStateReviewed,
  setSingleImageReference,
  acceptResult,
  reconcileCompiledVideoResults,
} from "./graph";
import { PromptLibrary } from "./PromptLibrary";
import { ModelSelector } from "./ModelSelector";
import { ImageGenerationSettings } from "./ImageGenerationSettings";
import {MotionReferenceEditor} from './components/MotionReferenceEditor';
import {videoModeLabels} from './motionReference';
import { PlatformModels } from "./PlatformModels";
import { GenerationPolicyPanel } from "./GenerationPolicyPanel";
import { VisualStylePicker } from "./VisualStylePicker";
import type { GenerationPolicy } from "./generationPolicy";
import { FilmBiblePanel } from "./filmBible/FilmBiblePanel";
import {
  bindVisualVersion,
  renameVisualCard,
  restoreVisualCard,
  setVisualVersionStatus,
  softDeleteVisualCard,
  unbindVisualVersion,
  updateDraftVisualVersion,
} from "./filmBible/commands";
import {
  forkLockedVisualVersion,
  setProjectVisualStyle,
  upgradeVisualBindings,
} from "./filmBible/versioning";
import {
  acceptVisualReferenceResult,
  attachUploadedPrimaryReference,
  isStateCard,
  lockVisualVersion,
  planVisualReferenceGeneration,
  resolveVisualGenerationTarget,
  setVisualCardImageOverride,
  visualAssetCategory,
} from "./filmBible/references";
import {
  deriveManagedGraph,
  filterManagedEdgeRemovals,
  isManagedVisualNode,
  visualVersionIdFromNode,
} from "./filmBible/managedGraph";
import {
  VisualAssetNode,
  VisualBibleGraphProvider,
} from "./filmBible/VisualAssetNode";
import { visualBibleOf } from "./filmBible/types";
import type { VoiceProfile } from "./filmBible/types";
import { requireTtsVoice, chooseVoiceVersion, acceptVoiceResult, saveVoiceProfile, setVoiceLocked, voiceProfilesOf, voiceParameters } from "./filmBible/voices";
import {resolvedVoice,voiceCardId} from './filmBible/voiceResolution';
import { catalogVoice, CUSTOM_VOICE_ID, DOUBAO_TTS2_VOICES } from "./filmBible/voiceCatalog";
import { StoryboardWorkspace } from "./pages/StoryboardWorkspace";
import { VideoProductionWorkspace } from "./pages/VideoProductionWorkspace";
import { TaskCenter } from "./pages/TaskCenter";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import {
  createStoryboardShot,
  moveStoryboardShot,
  selectedShotImageNodeIds,
  selectedShotVideoNodeIds,
  shotIdentity,
  updateStoryboardShot,
} from "./storyboard";
import { deriveVideoProductionRows, validateVideoSubmission } from "./videoProduction";
import { RunWorkflow } from "./RunWorkflow";
import { PanoramaViewer } from "./PanoramaViewer";
import { defaultStage } from "./directorScene";
const DirectorStage = lazy(() =>
  import("./DirectorStage").then((m) => ({ default: m.DirectorStage })),
);
import { framesForDuration, migrateLinkedNodePrompts, updateLinkedNodePrompt, updateShot } from "./shotSync";
import { TimelinePreview } from "./TimelinePreview";
import type { Clip } from "./timeline";
import type { EditorDocument } from "./editor/editorDocument";
import { AnYingMark } from "./app/AnYingMark";
import { GlobalNav, type GlobalPanel } from "./app/GlobalNav";
import { planGlobalPanelAction } from "./app/globalNavigation";
import { WorkflowStageNav } from "./app/WorkflowStageNav";
import { WorkflowGuideBanner } from "./app/WorkflowGuideBanner";
import { deriveWorkflowGuide } from "./app/workflowGuide";
import {
  defaultViewForStage,
  parseWorkflowStage,
  workflowStageScope,
  workflowStageUrl,
  type WorkflowStage,
} from "./app/workflow";
import { WorkflowOverview } from "./pages/WorkflowOverview";
import { SourceLibraryPage } from "./pages/SourceLibraryPage";
import { AdaptationPage } from "./pages/AdaptationPage";
import { ScriptRoomPage } from "./pages/ScriptRoomPage";
import { ArtDepartmentPage } from "./pages/ArtDepartmentPage";
import { ProductionAssetCenter } from "./pages/ProductionAssetCenter";
import { EpisodeSelector } from "./app/EpisodeSelector";
import {
  episodeLabel,
  episodesForProduction,
  type EpisodeSummary,
  type ProductionSummary,
} from "./app/production";
import { ProductionLibrary } from "./pages/ProductionLibrary";
import { CollaborationClient } from "./collaborationClient";
import { CollaborationPanel } from "./CollaborationPanel";
import { reconcileTimelineEdit } from "./editor/legacyTimeline";
import { ProjectSetupDialog } from "./pages/ProjectSetupDialog";
import {
  applyRatioChange,
  applyTargetDuration,
  applyVideoResolution,
  applyVideoOutputSetting,
  bibleFields,
  mergeBibleFields,
  projectSetupPayload,
  type ProjectSetupDraft,
} from "./projectSetup";
const EditorWorkspace = lazy(() =>
  import("./editor/EditorWorkspace").then((module) => ({
    default: module.EditorWorkspace,
  })),
);

type Any = Record<string, any>;
type Asset = {
  id: string;
  name: string;
  kind: string;
  url: string;
  metadata: Any;
  category: string;
  source: string;
};
type Job = {
  id: string;
  submission_id?: string;
  kind: string;
  node_id: string;
  status: string;
  phase: string;
  progress: number | null;
  error: string;
  input: Any;
  result: Any;
  created: number;
  provider_job_id?: string;
};
type VisualUsage = {
  version_id: string;
  episodes: Array<{ project_id: string; episode_no: number; episode_title: string }>;
  shots: Array<{ project_id: string; episode_no: number; shot_uid: string; shot_id: string }>;
};
type Doc = {
  schemaVersion: number;
  filmBible: Any;
  generationPolicy: GenerationPolicy;
  nodes: Node[];
  edges: Edge[];
  shots: Any[];
  timeline: Clip[];
  characters: Any[];
  brief: string;
  style: string;
  ratio: string;
  duration: number;
  videoResolution: string;
  videoRatio?: string;
  videoDuration?: number;
  videoFormat?: string;
  applied?: string[];
  editor?: EditorDocument;
};
type Project = EpisodeSummary & { document: Doc; production_revision: number; objects?: Any[]; object_collaboration?: boolean };
type SyncFailureKind = "api" | "sse" | "media";
type SyncFailure = {
  kind: SyncFailureKind;
  message: string;
  url: string;
};
const titles: Any = {
  text: "剧本",
  storyboard: "分镜规划",
  image: "图像",
  video: "视频",
  audio: "角色配音",
  reference: "参考素材",
};
const icons: Any = {
  text: FileText,
  storyboard: Layers,
  image: ImageIcon,
  video: Film,
  audio: FileText,
  reference: FolderOpen,
};
const states: Any = {
  queued: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "待恢复",
};
const assetCategories: Any = {
  character: "角色",
  scene: "场景",
  prop: "道具",
  shot: "分镜",
  music: "音乐",
  sfx: "音效",
  voice: "人声",
  reference: "参考",
  other: "其他",
};
const assetKinds: Any = { image: "图片", video: "视频", audio: "音频", subtitle: "字幕" };
const debugUrl = (url: string) => {
  if (typeof window === "undefined") return url;
  try {
    return new URL(url, window.location.origin).toString();
  } catch {
    return url;
  }
};
const api = async (path: string, options: RequestInit = {}) => {
  const url = "/api" + path;
  const requestUrl = debugUrl(url);
  try {
    const r = await fetch(url, {
      ...options,
      headers:
        options.body instanceof FormData
          ? { ...options.headers, ...(document.cookie.match(/(?:^|; )ovc_csrf=([^;]+)/)?.[1]
              ? { "X-CSRF-Token": decodeURIComponent(document.cookie.match(/(?:^|; )ovc_csrf=([^;]+)/)![1]) }
              : {}) }
          : { "Content-Type": "application/json", ...options.headers,
              ...(document.cookie.match(/(?:^|; )ovc_csrf=([^;]+)/)?.[1]
                ? { "X-CSRF-Token": decodeURIComponent(document.cookie.match(/(?:^|; )ovc_csrf=([^;]+)/)![1]) }
                : {}) },
    });
    if (!r.ok) {
      const error = await readApiErrorMessage(r);
      throw Object.assign(
        new Error(error),
        { kind: "api", status: r.status, url: requestUrl },
      );
    }
    return await r.json();
  } catch (cause: any) {
    if (cause?.url) throw cause;
    throw Object.assign(
      new Error(cause?.message || "API 请求失败"),
      { kind: "api", url: requestUrl },
    );
  }
};
const send = (method: string, value?: unknown): RequestInit => ({
  method,
  body: value === undefined ? undefined : JSON.stringify(value),
});
const id = () => {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  );
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};
function dialoguePerformance(shot: Any, dialogue: Any, profile: Any) {
  const dialogueEmotion = String(dialogue?.emotion || "").trim();
  const shotEmotion = String(shot?.emotion || "").trim();
  const defaultEmotion = String(profile?.parameters?.emotion || "").trim();
  const emotion = dialogueEmotion || shotEmotion || defaultEmotion;
  const parts = [
    shot?.scene ? `场景：${shot.scene}` : "",
    shot?.action ? `镜头动作：${shot.action}` : "",
    shotEmotion ? `全镜情绪：${shotEmotion}` : "",
    emotion ? `本句表演：${emotion}` : "请根据台词语义自然演绎",
    "保持角色既定声纹，语气与影片表演同步，不要用播报腔",
  ].filter(Boolean);
  return {
    emotion,
    contextTexts: [`影片对白表演指令。${parts.join("；")}。`],
  };
}
function Media({
  asset,
  controls = true,
  retryKey = 0,
  onFailure,
  onReady,
}: {
  asset?: Asset | Any;
  controls?: boolean;
  retryKey?: number;
  onFailure?: (asset: Asset | Any) => void;
  onReady?: (asset: Asset | Any) => void;
}) {
  if (!asset)
    return (
      <div className="media-empty">
        <ImageIcon size={30} />
        <span>等待生成或引用素材</span>
      </div>
  );
  return asset.kind === "video" ? (
    <video
      key={`${asset.id || asset.url}-${retryKey}`}
      src={asset.url}
      controls={controls}
      preload="metadata"
      onError={() => onFailure?.(asset)}
      onLoadedData={() => onReady?.(asset)}
    />
  ) : asset.kind === "audio" ? (
    <audio
      key={`${asset.id || asset.url}-${retryKey}`}
      src={asset.url}
      controls
      onError={() => onFailure?.(asset)}
      onCanPlay={() => onReady?.(asset)}
    />
  ) : (
    <img
      key={`${asset.id || asset.url}-${retryKey}`}
      src={asset.url}
      alt={asset.name}
      onError={() => onFailure?.(asset)}
      onLoad={() => onReady?.(asset)}
    />
  );
}
function MediaNode({ data, selected }: { data: Any; selected?: boolean }) {
  const Icon = icons[data.kind] || Layers;
  const job = data.job as Job | undefined;
  return (
    <div className={"media-node " + (selected ? "selected" : "")}>
      <Handle type="target" position={Position.Left} />
      <div className="node-heading">
        <Icon size={15} />
        <span>{data.label || titles[data.kind]}</span>
        <small>
          {data.model_id && data.model_id !== "local" ? "外部 API" : "未配置"}
        </small>
      </div>
      <div
        className={
          "node-content " +
          (["text", "storyboard"].includes(data.kind) ? "text-content" : "")
        }
      >
        {data.asset ? (
          <Media
            asset={data.asset}
            controls={false}
            retryKey={data.mediaRetryKey}
            onFailure={data.onMediaFailure}
            onReady={data.onMediaReady}
          />
        ) : data.text ? (
          <p>{data.text}</p>
        ) : ["text", "storyboard"].includes(data.kind) ? (
          <div className="node-empty">
            <Icon size={26} />
            <p>
              {data.kind === "text"
                ? "从一个故事开始"
                : "把故事拆成可拍摄的镜头"}
            </p>
          </div>
        ) : (
          <div className="node-empty">
            <Icon size={32} />
            <p>
              {data.kind === "image" ? "描绘故事的第一个瞬间" : "让画面动起来"}
            </p>
          </div>
        )}
      </div>
      <div className="node-footer">
        <span>
          {data.stale
            ? "输入已更改 · 可重新生成"
            : job
              ? states[job.status]
              : "准备创作"}
        </span>
        {job?.status === "running" ? (
          <LoaderCircle size={14} className="spin" />
        ) : data.asset || data.text ? (
          <Check size={14} />
        ) : (
          <span className="node-hint">选择以编辑 →</span>
        )}
      </div>
      {job?.status === "running" && (
        <div className="node-progress">
          <div
            style={{
              width:
                job.progress == null ? "30%" : Math.max(2, job.progress) + "%",
            }}
          />
        </div>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { media: MediaNode, visualAsset: VisualAssetNode };

function Auth({ onLogin }: { onLogin: (status: Any) => void }) {
  const [status, setStatus] = useState<Any>();
  const [mode, setMode] = useState<"login" | "register" | "reset">("login");
  const [phone, setPhone] = useState("");
  const [nickname, setNickname] = useState("");
  const [token, setToken] = useState(new URLSearchParams(window.location.search).get("invite") || new URLSearchParams(window.location.search).get("reset") || "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/auth/status")
      .then(setStatus)
      .catch((e) => setError(e.message));
  }, []);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const path = mode === "login" ? "/auth/login" : mode === "register" ? "/auth/register" : "/auth/password-reset";
      const body = mode === "login" ? { phone, password }
        : mode === "register" ? { invitation_token: token, phone, nickname, password }
        : { token, password };
      await api(path, send("POST", body));
      onLogin(await api("/auth/status"));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <div className="auth-art">
        <div className="brand">
          <AnYingMark size={29} />
          安影 <small>STUDIO</small>
        </div>
        <div className="auth-lines">
          <span>01 / STORY</span>
          <span>02 / FRAME</span>
          <span>03 / MOTION</span>
        </div>
        <h1>
          让一个念头，
          <br />
          成为一部短片。
        </h1>
        <p>你的故事，你的模型，你的工作室。</p>
        <div className="auth-meta">
          <Monitor size={18} /> 浏览器创作 · 外部模型 API
        </div>
      </div>
      <form onSubmit={submit} className="auth-form">
        <span className="eyebrow">YOUR CREATIVE SPACE</span>
        <h2>{mode === "login" ? "登录安影" : mode === "register" ? "接受邀请" : "设置新密码"}</h2>
        <p>{mode === "login" ? "使用你的手机号和个人密码进入获权团队。" : mode === "register" ? "邀请码只提供注册资格，团队负责人确认后才能看到作品。" : "使用管理员线下核验后签发的一次性链接。"}</p>
        {mode !== "reset" && <label>
          手机号
          <input autoFocus type="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="例如 138 0000 0000" required />
        </label>}
        {mode === "register" && <label>
          昵称
          <input value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={80} required />
        </label>}
        {mode !== "login" && <label>
          {mode === "register" ? "邀请码" : "重置令牌"}
          <input value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" required />
        </label>}
        <label>
          个人密码
          <input
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={mode === "login" ? 1 : 15}
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === "login" ? "输入密码" : "15–128 位口令"}
            required
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button
          className="primary"
          disabled={busy || !status}
        >
          {busy ? (
            <LoaderCircle className="spin" size={17} />
          ) : (
            <ArrowUpRight size={17} />
          )}{" "}
          {mode === "login" ? "进入工作室" : mode === "register" ? "注册并登录" : "重置并登录"}
        </button>
        <div className="auth-switch">
          <button type="button" className="quiet" onClick={() => setMode(mode === "login" ? "register" : "login")}>{mode === "login" ? "我有邀请码" : "返回登录"}</button>
          {mode !== "reset" && <button type="button" className="quiet" onClick={() => setMode("reset")}>使用重置链接</button>}
        </div>
      </form>
    </div>
  );
}

function WaitingForWorkspace({ session, onLogout }: { session: Any; onLogout: () => void }) {
  return <div className="empty-workspace account-page">
    <AnYingMark size={64}/><span className="eyebrow">ACCOUNT READY</span>
    <h1>等待加入团队</h1>
    <p>{session.user?.nickname}，你的个人账号已创建。邀请码不会自动授予团队权限，请将用户 ID <code>{session.user?.id}</code> 发给团队 owner 确认入组。</p>
    <button className="quiet" onClick={async()=>{await api('/auth/logout',send('POST'));onLogout();}}>退出登录</button>
  </div>;
}

function AdminConsole({ session, onLogout }: { session: Any; onLogout: () => void }) {
  const [users,setUsers]=useState<Any[]>([]),[workspaces,setWorkspaces]=useState<Any[]>([]),[invitations,setInvitations]=useState<Any[]>([]);
  const [notice,setNotice]=useState(''),[error,setError]=useState('');
  const [inviteToken,setInviteToken]=useState(''),[resetToken,setResetToken]=useState(''),[workspaceName,setWorkspaceName]=useState(''),[ownerId,setOwnerId]=useState('');
  const load=async()=>{try{const [u,w,i]=await Promise.all([api('/admin/users'),api('/admin/workspaces'),api('/admin/invitations')]);setUsers(u);setWorkspaces(w);setInvitations(i);}catch(e:any){setError(e.message);}};
  useEffect(()=>{void load();},[]);
  if(session.user?.platform_role!=='platform_admin') return <div className="empty-workspace"><h1>无权访问</h1><a href="/">返回工作室</a></div>;
  return <div className="admin-page">
    <header><div><span className="eyebrow">PLATFORM ADMIN</span><h1>平台管理</h1></div><div><a className="quiet" href="/">返回工作室</a><button onClick={async()=>{await api('/auth/logout',send('POST'));onLogout();}}>退出</button></div></header>
    {error&&<div className="error">{error}</div>}{notice&&<div className="notice">{notice}</div>}
    <PlatformModels request={api}/>
    <section><h2>注册邀请</h2><p>原始令牌只显示一次，不写入日志。</p><button className="primary" onClick={async()=>{try{const item=await api('/admin/invitations',send('POST',{expires_hours:48}));setInviteToken(item.token);setNotice('已创建 48 小时一次性邀请');await load();}catch(e:any){setError(e.message);}}}>创建邀请</button>{inviteToken&&<code className="one-time-token">{inviteToken}</code>}
      <div className="admin-list">{invitations.map(i=><div key={i.id}><code>{i.id}</code><span>{i.consumed_at?'已使用':i.revoked_at?'已撤销':'可用'}</span>{!i.consumed_at&&!i.revoked_at&&<button onClick={async()=>{await api(`/admin/invitations/${i.id}`,send('DELETE'));await load();}}>撤销</button>}</div>)}</div>
    </section>
    <section><h2>用户</h2><p>重置令牌仅显示一次，请通过受控渠道交给本人。</p>{resetToken&&<code className="one-time-token">{resetToken}</code>}<div className="admin-list">{users.map(u=><div key={u.id}><span><b>{u.nickname}</b><small>{u.phone} · {u.id}</small></span><em>{u.platform_role}</em><button disabled={!u.is_active} onClick={async()=>{try{setError('');const item=await api('/admin/password-resets',send('POST',{user_id:u.id,expires_minutes:30}));setResetToken(item.token);setNotice(`已为 ${u.nickname} 签发 30 分钟一次性重置令牌`);}catch(e:any){setError(e.message);}}}>签发重置</button><button disabled={u.id===session.user.id} onClick={async()=>{try{setError('');await api(`/admin/users/${u.id}`,send('PATCH',{is_active:!u.is_active}));await load();}catch(e:any){setError(e.message);}}}>{u.is_active?'停用':'启用'}</button></div>)}</div></section>
    <section><h2>创建团队并指定 owner</h2><div className="inline-fields"><input placeholder="团队名称" value={workspaceName} onChange={e=>setWorkspaceName(e.target.value)}/><input placeholder="Owner user_id" value={ownerId} onChange={e=>setOwnerId(e.target.value)}/><button onClick={async()=>{try{await api('/admin/workspaces',send('POST',{name:workspaceName,owner_user_id:ownerId}));setWorkspaceName('');setOwnerId('');await load();}catch(e:any){setError(e.message);}}}>创建</button></div><div className="admin-list">{workspaces.map(w=><div key={`${w.id}:${w.owner_user_id}`}><b>{w.name}</b><code>{w.id}</code><span>owner · {w.owner_nickname} · {w.owner_user_id}</span></div>)}</div></section>
  </div>;
}

function MembershipConsole({ session, onLogout }: { session: Any; onLogout: () => void }) {
  const [workspaceId,setWorkspaceId]=useState(session.workspaces?.[0]?.id||''),[members,setMembers]=useState<Any[]>([]),[productions,setProductions]=useState<Any[]>([]),[productionId,setProductionId]=useState(''),[productionMembers,setProductionMembers]=useState<Any[]>([]);
  const [workspaceUserId,setWorkspaceUserId]=useState(''),[workspaceRole,setWorkspaceRole]=useState('member');
  const [productionUserId,setProductionUserId]=useState(''),[productionRole,setProductionRole]=useState('viewer'),[error,setError]=useState('');
  const load=async()=>{try{const [m,p]=await Promise.all([api(`/workspaces/${workspaceId}/members`),api(`/productions?workspace_id=${encodeURIComponent(workspaceId)}`)]);setMembers(m);setProductions(p);setProductionId(p[0]?.id||'');setProductionMembers([]);}catch(e:any){setError(e.message);}};
  useEffect(()=>{if(workspaceId)void load();},[workspaceId]);
  useEffect(()=>{if(productionId)api(`/productions/${productionId}/members`).then(setProductionMembers).catch((e:any)=>setError(e.message));},[productionId]);
  const canManageWorkspace=session.workspaces.some((workspace:Any)=>workspace.id===workspaceId&&workspace.role==='owner');
  const selectedProduction=productions.find((production:Any)=>production.id===productionId);
  const canManageProduction=selectedProduction?.role==='owner'||selectedProduction?.role==='manager';
  return <div className="admin-page"><header><div><span className="eyebrow">TEAM ACCESS</span><h1>团队与作品成员</h1></div><div><a href="/">返回工作室</a>{session.user?.platform_role==='platform_admin'&&<a href="/admin">平台管理</a>}<button onClick={async()=>{await api('/auth/logout',send('POST'));onLogout();}}>退出</button></div></header>{error&&<div className="error">{error}</div>}
    <label>团队<select value={workspaceId} onChange={e=>setWorkspaceId(e.target.value)}>{session.workspaces.map((w:Any)=><option key={w.id} value={w.id}>{w.name} · {w.role}</option>)}</select></label>
    <section><h2>团队成员</h2>{canManageWorkspace?<div className="inline-fields"><input placeholder="已注册用户 ID" value={workspaceUserId} onChange={e=>setWorkspaceUserId(e.target.value)}/><select value={workspaceRole} onChange={e=>setWorkspaceRole(e.target.value)}><option value="member">member</option><option value="owner">owner</option></select><button onClick={async()=>{try{setError('');await api(`/workspaces/${workspaceId}/members/${workspaceUserId}`,send('PUT',{role:workspaceRole}));setWorkspaceUserId('');await load();}catch(e:any){setError(e.message);}}}>确认入组</button></div>:<p className="muted">只有团队 owner 可以确认入组或调整团队角色。</p>}<div className="admin-list">{members.map(m=><div key={m.id}><span><b>{m.nickname}</b><small>{m.id} · {m.phone}</small></span><em>{m.role}</em>{canManageWorkspace&&<button className="danger" onClick={async()=>{if(!window.confirm(`确认将 ${m.nickname} 移出团队？其作品权限也会撤销。`))return;try{setError('');await api(`/workspaces/${workspaceId}/members/${m.id}`,send('DELETE'));await load();}catch(e:any){setError(e.message);}}}>移出团队</button>}</div>)}</div></section>
    <section><h2>作品成员</h2>{productions.length?<select value={productionId} onChange={e=>setProductionId(e.target.value)}>{productions.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>:<p className="muted">当前团队没有你可见的作品。</p>}{canManageProduction&&<div className="inline-fields"><input placeholder="团队成员 user_id" value={productionUserId} onChange={e=>setProductionUserId(e.target.value)}/><select value={productionRole} onChange={e=>setProductionRole(e.target.value)}><option value="viewer">viewer</option><option value="editor">editor</option><option value="manager">manager</option></select><button disabled={!productionId} onClick={async()=>{try{setError('');await api(`/productions/${productionId}/members/${productionUserId}`,send('PUT',{role:productionRole}));setProductionUserId('');setProductionMembers(await api(`/productions/${productionId}/members`));}catch(e:any){setError(e.message);}}}>授权作品</button></div>}{productionId&&!canManageProduction&&<p className="muted">只有作品 manager 或团队 owner 可以调整作品成员。</p>}<div className="admin-list">{productionMembers.map(m=><div key={m.id}><b>{m.nickname}</b><code>{m.id}</code><em>{m.role}</em>{canManageProduction&&<button className="danger" onClick={async()=>{if(!window.confirm(`确认移除 ${m.nickname} 的作品权限？`))return;try{setError('');await api(`/productions/${productionId}/members/${m.id}`,send('DELETE'));setProductionMembers(await api(`/productions/${productionId}/members`));}catch(e:any){setError(e.message);}}}>移除作品权限</button>}</div>)}</div></section>
  </div>;
}

function Studio() {
  const [session, setSession] = useState<Any | null | undefined>(undefined);
  useEffect(() => {
    api("/auth/status")
      .then((s) => setSession(s.authenticated ? s : null))
      .catch(() => setSession(null));
  }, []);
  if (session === undefined)
    return (
      <div className="loading">
        <LoaderCircle className="spin" />
        正在连接工作室
      </div>
    );
  if (!session) return <Auth onLogin={(value) => setSession(value)} />;
  if (window.location.pathname === "/admin") return <AdminConsole session={session} onLogout={() => setSession(null)} />;
  if (window.location.pathname === "/members") return <MembershipConsole session={session} onLogout={() => setSession(null)} />;
  if (!session.workspaces?.length) return <WaitingForWorkspace session={session} onLogout={() => setSession(null)} />;
  const taskId = new URLSearchParams(window.location.search).get("task");
  if (taskId) return <TaskDetailPage jobId={taskId} request={api} />;
  return (
    <ReactFlowProvider>
      <Workspace session={session} onLogout={() => setSession(null)} />
    </ReactFlowProvider>
  );
}

function Workspace({ session, onLogout }: { session: Any; onLogout: () => void }) {
  const sourceDrafts=useRef(new OwnedContentDrafts('chapter'));
  const scriptDrafts=useRef(new OwnedContentDrafts('script'));
  const ownedUnsaved=()=>sourceDrafts.current.unsaved||scriptDrafts.current.unsaved;
  function requireOwnedSaved(){if(ownedUnsaved())throw new Error('原著或剧本仍有未保存草稿；请回到对应页面保存、比较或明确放弃后再切换作品/分集。');}
  useEffect(()=>{
    const guard=(event:BeforeUnloadEvent)=>{if(ownedUnsaved()){event.preventDefault();event.returnValue='';}};
    window.addEventListener('beforeunload',guard);return()=>window.removeEventListener('beforeunload',guard);
  },[]);
  const collaboration = useRef<CollaborationClient | null>(null);
  if (!collaboration.current) collaboration.current = new CollaborationClient(api, session.user.id);
  const collaborationAssets = useRef<Asset[]>([]);
  const projectOpenSequence = useRef(0);
  const initialWorkflowStage = parseWorkflowStage(window.location.search);
  const [productions, setProductions] = useState<ProductionSummary[]>([]),
    [projects, setProjects] = useState<EpisodeSummary[]>([]),
    [project, setProject] = useState<Project | null>(null),
    [doc, setDoc] = useState<Doc | null>(null),
    [assets, setAssets] = useState<Asset[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [visualUsage, setVisualUsage] = useState<VisualUsage[]>([]),
    [workflowContext, setWorkflowContext] = useState<Any>({ adaptation: null, scripts: [] }),
    [system, setSystem] = useState<Any>({
      models: [],
      templates: {},
    }),
    [config, setConfig] = useState<Any>({
      models: [],
    });
  collaborationAssets.current = assets;
  const [activeWorkspaceId,setActiveWorkspaceId]=useState<string>(session.workspaces[0].id);
  const canCreateProduction = session.workspaces.some(
    (workspace: Any) => workspace.id === activeWorkspaceId && workspace.role === "owner",
  );
  const [workflowStage, setWorkflowStage] = useState<WorkflowStage>(initialWorkflowStage);
  const [selected, setSelected] = useState<string | null>(null),
    [view, setView] = useState(defaultViewForStage(initialWorkflowStage)),
    [panel, setPanel] = useState<string | null>(null),
    [notice, setNotice] = useState(""),
    [error, setError] = useState(""),
    [saved, setSaved] = useState("已保存"),
    [busy, setBusy] = useState(false),
    [timelineOpen, setTimelineOpen] = useState(false),
    [revisions, setRevisions] = useState<Any[]>([]),
    [trashItems, setTrashItems] = useState<Any>({ projects: [], assets: [], sources: [], chapters: [] }),
    [preview, setPreview] = useState<Asset | null>(null);
  const [workflowDataRevision, setWorkflowDataRevision] = useState({ source: 0, adaptation: 0, script: 0 });
  const [previewTimeline, setPreviewTimeline] = useState(false);
  const [exportSource, setExportSource] = useState<"legacy" | "editor">("legacy");
  const [editorExportTimeline, setEditorExportTimeline] = useState<EditorDocument["timeline"] | undefined>();
  const [booted, setBooted] = useState(false);
  const [projectSetupOpen, setProjectSetupOpen] = useState(false);
  const [projectSetupKey, setProjectSetupKey] = useState(0);
  const [projectSettingsTab, setProjectSettingsTab] = useState<"production" | "episode">("production");
  const [productionNameDraft, setProductionNameDraft] = useState("");
  const [visualStyleDraft, setVisualStyleDraft] = useState("");
  const [visualFocus, setVisualFocus] = useState<string | undefined>();
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [panorama, setPanorama] = useState<Asset | null>(null);
  const [syncFailure, setSyncFailure] = useState<SyncFailure | null>(null);
  const [mediaRetryKey, setMediaRetryKey] = useState(0);
  const [pendingAutoRunNodeId, setPendingAutoRunNodeId] = useState<string | null>(null);
  const [uploadCategory, setUploadCategory] = useState("other");
  const [conflict, setConflict] = useState(false),
    [recoveryBusy, setRecoveryBusy] = useState(false);
  const conflictRef = useRef(false);
  const storyboardSubmissionRef = useRef(false);
  const workflowStageRef = useRef<WorkflowStage>(initialWorkflowStage);
  const revision = useRef(1),
    productionRevision = useRef(1),
    dirty = useRef(false),
    current = useRef<{ project: Project | null; doc: Doc | null }>({
      project: null,
      doc: null,
    }),
    saving = useRef(false),
    saveFlight = useRef<Promise<void> | null>(null),
    refreshFlights = useRef(new Map<string, Promise<void>>()),
    nodeMeasurements = useRef(
      new Map<string, { width?: number; height?: number }>(),
    ),
    fileInput = useRef<HTMLInputElement>(null),
    observedCompletedJobs = useRef(new Set<string>()),
    observedCandidateJobs = useRef(new Set<string>()),
    { fitView } = useReactFlow(),
    updateNodeInternals = useUpdateNodeInternals();
  const [layoutVersion, setLayoutVersion] = useState(0);
  current.current = { project, doc };
  workflowStageRef.current = workflowStage;
  useEffect(() => {
    if (!project) return;
    const active = productions.find((item) => item.id === project.production_id);
    if (active) setProductionNameDraft(active.name);
  }, [project?.production_id, productions]);
  useEffect(() => {
    if (doc) setVisualStyleDraft(doc.style);
  }, [project?.id, doc?.style]);
  function activateWorkflowStage(
    next: WorkflowStage,
    historyMode: "push" | "replace" | "none" = "push",
  ) {
    if(next!==workflowStageRef.current&&ownedUnsaved())setNotice('原著/剧本草稿已保留在当前作品；返回对应页面后可以继续保存或比较。');
    workflowStageRef.current = next;
    setWorkflowStage(next);
    if (historyMode !== "none") {
      const nextUrl = workflowStageUrl(window.location.href, next);
      window.history[historyMode === "replace" ? "replaceState" : "pushState"](
        null,
        "",
        nextUrl,
      );
    }
    setPanel(null);
    if (next === "storyboard" && ["shots", "director"].includes(view)) return;
    if (next === "images" && ["shots", "grid"].includes(view)) return;
    setView(defaultViewForStage(next));
  }
  const report = (e: any) => {
    const message = e?.message || String(e);
    setError(e?.url ? `${message}（开发调试：${e.url}）` : message);
  };
  const reportMediaFailure = useCallback((asset: Asset | Any) => {
    setSyncFailure({
      kind: "media",
      message: "媒体文件加载失败，已保留画布和素材，等待网络恢复后重试",
      url: debugUrl(asset.url),
    });
  }, []);
  const clearMediaFailure = useCallback((asset: Asset | Any) => {
    const url = debugUrl(asset.url);
    setSyncFailure((previous) =>
      previous?.kind === "media" && previous.url === url ? null : previous,
    );
  }, []);
  const update = useCallback((fn: (d: Doc) => Doc) => {
    const base = current.current.doc;
    if (!base) return;
    if ((current.current.project as Any)?.permissions?.can_generate === false) {
      setError("当前为只读成员；可以查看和评论，但不能编辑对象。");
      return;
    }
    let next:Doc;
    try {next=deriveManagedGraph(reconcileTimelineEdit(base,fn(base),collaborationAssets.current) as Doc);}
    catch(e:any){setError(e.message);return;}
    collaboration.current?.mark(next, collaborationAssets.current);
    current.current = { ...current.current, doc: next };
    setDoc(next);
    dirty.current = true;
    setSaved("未保存");
  }, []);
  const refresh = useCallback((pid: string) => {
    const pending = refreshFlights.current.get(pid);
    if (pending) return pending;
    const work = (async () => {
      try {
        // Treat assets and jobs as one snapshot. A partial response must never
        // replace the last known-good canvas state with an empty collection.
        const productionId = current.current.project?.id === pid
          ? current.current.project.production_id
          : undefined;
        const [a, j, usages, adaptation, scripts] = await Promise.all([
          api(`/projects/${pid}/assets?scope=production`),
          api(`/projects/${pid}/jobs`),
          productionId ? api(`/productions/${productionId}/visual-usage`) : Promise.resolve([]),
          productionId ? api(`/productions/${productionId}/adaptation`) : Promise.resolve(null),
          productionId ? api(`/productions/${productionId}/scripts`) : Promise.resolve([]),
        ]);
        if (current.current.project?.id === pid) {
          setAssets(a);
          setJobs(j);
          setVisualUsage(usages);
          setWorkflowContext({ adaptation, scripts });
        }
        setSyncFailure((previous) =>
          previous?.kind === "api" ? null : previous,
        );
      } catch (e: any) {
        setSyncFailure({
          kind: "api",
          message: "刷新失败，正在重试",
          url: e?.url || debugUrl(`/api/projects/${pid}/assets`),
        });
        throw e;
      }
    })();
    refreshFlights.current.set(pid, work);
    void work.then(
      () => refreshFlights.current.delete(pid),
      () => refreshFlights.current.delete(pid),
    );
    return work;
  }, []);
  async function openProject(pid: string) {
    requireOwnedSaved();
    if (dirty.current || saveFlight.current) await save();
    if (dirty.current)
      throw new Error("项目尚未保存，已保留当前编辑。请先解决保存冲突。");
    const openSequence = ++projectOpenSequence.current;
    // Only switch views after every part of the new project snapshot arrives.
    // This leaves the current canvas visible if a refresh fails mid-request.
    let p: Project, a: Asset[], j: Job[], usages: VisualUsage[], adaptation: Any, scripts: Any[];
    try {
      p = await api("/projects/" + pid);
      [a, j, usages, adaptation, scripts] = await Promise.all([
        api(`/projects/${pid}/assets?scope=production`),
        api(`/projects/${pid}/jobs`),
        api(`/productions/${p.production_id}/visual-usage`),
        api(`/productions/${p.production_id}/adaptation`),
        api(`/productions/${p.production_id}/scripts`),
      ]);
    } catch (e: any) {
      setSyncFailure({
        kind: "api",
        message: "刷新失败，正在重试",
        url: e?.url || debugUrl(`/api/projects/${pid}`),
      });
      throw e;
    }
    if (openSequence !== projectOpenSequence.current) return;
    requireOwnedSaved();
    if(dirty.current||saveFlight.current)throw new Error('载入期间当前作品又有编辑，已保留草稿；请先保存再切换。');
    const migratedDocument = migrateLinkedNodePrompts(p.document);
    const projectedDocument = deriveManagedGraph(migratedDocument);
    const openedProject = { ...p, document: projectedDocument };
    revision.current = p.revision;
    productionRevision.current = p.production_revision;
    dirty.current = false;
    collaboration.current!.open({...openedProject,document:projectedDocument}, a);
    // Update the imperative snapshot before scheduling React state changes.
    // This prevents an autosave tick from pairing the new project id with the
    // previous project's document while the project switch is being rendered.
    current.current = { project: openedProject, doc: projectedDocument };
    nodeMeasurements.current.clear();
    setLayoutVersion((value) => value + 1);
    setProject(openedProject);
    setDoc(projectedDocument);
    setAssets(a);
    setJobs(j);
    setVisualUsage(usages);
    setWorkflowContext({ adaptation, scripts });
    setSelected(null);
    setHoveredNode(null);
    setVisualFocus(undefined);
    setPreview(null);
    setPreviewTimeline(false);
    setPanorama(null);
    setTimelineOpen(false);
    setView(defaultViewForStage(workflowStageRef.current));
    setSaved("已保存");
    setPanel(null);
    setTimeout(() => {
      fitView({ padding: 0.2 });
    }, 100);
  }
  async function boot() {
    try {
      const [productionList, list, sys, settings] = await Promise.all([
        api(`/productions?workspace_id=${encodeURIComponent(activeWorkspaceId)}`),
        api(`/projects?workspace_id=${encodeURIComponent(activeWorkspaceId)}`),
        api("/system"),
        api("/settings"),
      ]);
      setProductions(productionList);
      setProjects(list);
      setSystem(sys);
      setConfig({...settings,models:(settings.models||[]).map((model:Any)=>({...model,is_default:settings.defaults?.[model.kind]===model.id}))});
      if (list.length) await openProject(list[0].id);
      else setProjectSetupOpen(false);
    } catch (e) {
      report(e);
    } finally {
      setBooted(true);
    }
  }
  useEffect(() => {
    window.history.replaceState(
      null,
      "",
      workflowStageUrl(window.location.href, workflowStageRef.current),
    );
    const onPopState = () =>
      activateWorkflowStage(parseWorkflowStage(window.location.search), "none");
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [view]);
  useEffect(() => {
    boot();
  }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    const events = new EventSource("/api/events");
    const eventsUrl = debugUrl("/api/events");
    events.onopen = () => {
      setSyncFailure((previous) =>
        previous?.kind === "sse" ? null : previous,
      );
      const pid = current.current.project?.id;
      if (pid) refresh(pid).catch(() => {});
    };
    events.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        const pid = current.current.project?.id;
        if(data.project_id===pid&&['chapter','script','source_deleted','source_chapters_deleted'].includes(data.type)){
          setWorkflowDataRevision(value=>({...value,
            source:value.source+Number(data.type!=='script'),
            script:value.script+Number(data.type==='script')}));
        }
        if (data.project_id === pid && data.type === "object" && data.object_id) {
          const generation = collaboration.current!.drafts.generation;
          void api(`/projects/${pid}/objects`).then((rows) => {
            if (current.current.project?.id !== pid || collaboration.current!.drafts.generation !== generation || !current.current.doc) return;
            const next = collaboration.current!.mergeRemoteRows(rows, current.current.doc, collaborationAssets.current,data.object_id) as Doc;
            acceptObjectDocument(next);
          }).catch(report);
        }
        if (data.project_id === pid && data.type === "production" && typeof data.revision === "number") {
          setProductions((items) => items.map((item) => item.id === current.current.project?.production_id ? { ...item, revision: data.revision } : item));
          if (!dirty.current && !saveFlight.current && data.revision !== productionRevision.current) {
            void api(`/projects/${pid}`).then((latest) => {
              if (current.current.project?.id !== pid || dirty.current || saveFlight.current) return;
              const projectedDocument = deriveManagedGraph(latest.document);
              const openedProject = { ...latest, document: projectedDocument };
              collaboration.current!.open(openedProject,collaborationAssets.current);
              revision.current = latest.revision;
              productionRevision.current = latest.production_revision;
              current.current = { project: openedProject, doc: projectedDocument };
              setProject(openedProject);
              setDoc(projectedDocument);
              setSaved("已同步");
            }).catch(report);
          }
        }
        if (data.project_id === pid && data.type === "project" && typeof data.revision === "number") {
          if (!dirty.current && !saveFlight.current && data.revision !== revision.current) {
            void api(`/projects/${pid}`).then((latest) => {
              if (current.current.project?.id !== pid || dirty.current || saveFlight.current) return;
              const projectedDocument = deriveManagedGraph(latest.document);
              const openedProject = { ...latest, document: projectedDocument };
              collaboration.current!.open(openedProject,collaborationAssets.current);
              revision.current = latest.revision;
              productionRevision.current = latest.production_revision;
              current.current = { project: openedProject, doc: projectedDocument };
              setProject(openedProject);
              setDoc(projectedDocument);
              setSaved("已同步");
            }).catch(report);
          }
        }
        if (data.project_id === pid && data.type === "job")
          refresh(pid!).catch(() => {});
      } catch {
        setSyncFailure({
          kind: "sse",
          message: "实时同步数据异常，正在重连",
          url: eventsUrl,
        });
      }
    };
    events.onerror = () => {
      setSyncFailure({
        kind: "sse",
        message: "实时同步已断开，正在重连",
        url: eventsUrl,
      });
    };
    const poll = setInterval(() => {
      const pid = current.current.project?.id;
      if (pid) refresh(pid).catch(() => {});
    }, 8000);
    const retryOnNetworkRecovery = () => {
      setMediaRetryKey((value) => value + 1);
      const pid = current.current.project?.id;
      if (pid) refresh(pid).catch(() => {});
    };
    window.addEventListener("online", retryOnNetworkRecovery);
    return () => {
      events.close();
      clearInterval(poll);
      window.removeEventListener("online", retryOnNetworkRecovery);
    };
  }, [refresh]);
  async function recoverConflict() {
    setRecoveryBusy(true);
    try {
      const snapshot = current.current;
      if (!snapshot.project || !snapshot.doc) return;
      const generation=collaboration.current!.drafts.generation;
      const latest = await api("/projects/" + snapshot.project.id);
      if(current.current.project?.id!==snapshot.project.id||collaboration.current!.drafts.generation!==generation)return;
      const backup = JSON.stringify(
        {
          format: "yingxu-project-draft-v1",
          project_id: snapshot.project.id,
          name: snapshot.project.name,
          revision: revision.current,
          production_revision: productionRevision.current,
          document: snapshot.doc,
        },
        null,
        2,
      );
      sessionStorage.setItem("yingxu-conflict-" + snapshot.project.id, backup);
      const url = URL.createObjectURL(
        new Blob([backup], { type: "application/json" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `安影-冲突草稿-${Date.now()}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      revision.current = latest.revision;
      productionRevision.current = latest.production_revision;
      dirty.current = false;
      conflictRef.current = false;
      setConflict(false);
      collaboration.current!.open(latest,collaborationAssets.current);
      current.current={project:latest,doc:latest.document};
      setProject(latest);
      setDoc(latest.document);
      setSelected(null);
      setSaved("已保存");
      setError("");
      setNotice("本页草稿已下载备份，已载入主机最新版本");
    } catch (e) {
      report(e);
    } finally {
      setRecoveryBusy(false);
    }
  }
  async function save() {
    if (conflictRef.current) return;
    if (saveFlight.current) {
      await saveFlight.current;
      return save();
    }
    const snapshot = current.current;
    const projectSnapshot = snapshot.project;
    if (!projectSnapshot || !snapshot.doc || !dirty.current) return;
    const clientSnapshot=collaboration.current!,generationSnapshot=clientSnapshot.drafts.generation;
    const isCurrentScope=()=>current.current.project?.id===projectSnapshot.id&&
      collaboration.current===clientSnapshot&&clientSnapshot.drafts.generation===generationSnapshot;
    dirty.current = false;
    saving.current = true;
    setSaved("保存中");
    const name = projectSnapshot.name.trim() || "未命名短片";
    const work = (async () => {
      try {
        const result = await collaboration.current!.save(snapshot.doc!, name, collaborationAssets.current);
        if (!isCurrentScope()) return;
        revision.current = result.revision;
        productionRevision.current = result.production_revision;
        setProject((current) =>
          current?.id === projectSnapshot.id
            ? {
                ...current,
                name,
                episode_title: name,
                revision: result.revision,
                production_revision: result.production_revision,
                objects: result.objects,
              }
            : current,
        );
        if (name !== projectSnapshot.name) {
          setProjects((current) =>
            current.map((item) =>
              item.id === projectSnapshot.id
                ? { ...item, name, episode_title: name }
                : item,
            ),
          );
          setNotice("项目名称不能为空，已恢复为“未命名短片”");
        }
        setSaved(dirty.current ? "未保存" : "已保存");
      } catch (e: any) {
        if (!isCurrentScope()) return;
        dirty.current = true;
        if (e.status === 409) {
          conflictRef.current = true;
          setConflict(true);
          setSaved("保存冲突");
        } else {
          setSaved("保存失败");
          report(e);
        }
      } finally {
        saving.current = false;
      }
    })();
    saveFlight.current = work;
    try {
      await work;
    } finally {
      saveFlight.current = null;
    }
  }
  function acceptObjectDocument(next:Any) {
    const active=current.current.project;
    if(!active||!collaboration.current)return;
    const openedProject={...active,objects:[...collaboration.current.rows.values()]};
    current.current={project:openedProject,doc:next as Doc};
    setProject(openedProject);setDoc(next as Doc);
    dirty.current=collaboration.current.hasChanges(next,active.name,collaborationAssets.current);
    const hasConflict=[...collaboration.current.drafts.entries.values()].some(item=>item.state==='conflict');
    conflictRef.current=hasConflict;setConflict(hasConflict);
    setSaved(hasConflict?'保存冲突':dirty.current?'未保存':'已保存');
  }
  async function saveObject(id:string) {
    if(saveFlight.current)await saveFlight.current;
    const snapshot=current.current;
    if(!snapshot.doc||!snapshot.project)return;
    const clientSnapshot=collaboration.current!,generationSnapshot=clientSnapshot.drafts.generation;
    const work=(async()=>{
      try{
        await collaboration.current!.saveOnly(id,snapshot.doc!,collaborationAssets.current);
      }finally{
        if(current.current.project?.id===snapshot.project!.id&&current.current.doc&&
          collaboration.current===clientSnapshot&&clientSnapshot.drafts.generation===generationSnapshot)
          acceptObjectDocument(current.current.doc);
      }
    })();
    saveFlight.current=work;
    try{await work;}finally{saveFlight.current=null;}
  }
  async function saveCurrentView(){
    const stage=workflowStageRef.current;
    const store=stage==='source'?sourceDrafts.current:stage==='script'?scriptDrafts.current:null;
    if(!store)return save();
    if(!store.selectedId||!store.value(store.selectedId))return;
    setSaved('保存中');
    try{await store.save(store.selectedId,session.user.id,api);setSaved(ownedUnsaved()?'仍有未保存正文草稿':'已保存');}
    catch(error){setSaved('正文保存失败或冲突');throw error;}
    finally{setWorkflowDataRevision(value=>({...value,[stage]:value[stage as 'source'|'script']+1}));}
  }
  useEffect(() => {
    const interval = setInterval(() => {
      if (dirty.current) save();
    }, 2500);
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        void saveCurrentView().catch(report);
      }
    };
    window.addEventListener("keydown", key);
    return () => {
      clearInterval(interval);
      window.removeEventListener("keydown", key);
    };
  }, []);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);
  useEffect(() => {
    const completed = jobs.filter(job => job.status === "succeeded" && job.result && !observedCandidateJobs.current.has(job.id));
    completed.forEach(job => observedCandidateJobs.current.add(job.id));
    if (completed.length) setNotice(`有 ${completed.length} 个生成结果已完成；结果为候选，需明确采纳后才会修改对象。`);
  }, [jobs]);
  useEffect(() => {
    const completed = jobs.filter((job) => job.status === "succeeded");
    const newlyCompleted = completed.filter((job) => !observedCompletedJobs.current.has(job.id));
    completed.forEach((job) => observedCompletedJobs.current.add(job.id));
    const workflowCompleted = newlyCompleted.filter((job) =>
      ["source_analysis", "adaptation_generation", "script_generation"].includes(job.input?.stage),
    );
    if (workflowCompleted.length) {
      setWorkflowDataRevision((value) => ({
        source: value.source + Number(workflowCompleted.some((job) => job.input?.stage === "source_analysis")),
        adaptation: value.adaptation + Number(workflowCompleted.some((job) => ["source_analysis", "adaptation_generation"].includes(job.input?.stage))),
        script: value.script + Number(workflowCompleted.some((job) => job.input?.stage === "script_generation")),
      }));
      setNotice('文本生成已完成，结果仅作为候选保留；请在任务中心比较后明确采纳。');
    }
  }, [jobs]);
  useEffect(() => {
    const context = (document as any).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const register = (tool: Any) => {
      try {
        Promise.resolve(
          context.registerTool(tool, { signal: lifecycle.signal }),
        ).catch(() => {});
      } catch {}
    };
    register({
      name: "read_studio_project",
      title: "读取当前视频项目",
      description: "读取当前工作室项目的节点和分镜，不执行生成。",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
      annotations: { readOnlyHint: true, untrustedContentHint: true },
      execute: () => ({
        id: current.current.project?.id,
        name: current.current.project?.name,
        document: current.current.doc,
      }),
    });
    register({
      name: "stage_studio_nodes",
      title: "准备创作节点",
      description:
        "批量创建待编辑的文本、分镜、图像或视频节点。不提交模型任务，不产生云端费用。",
      inputSchema: {
        type: "object",
        properties: {
          nodes: {
            type: "array",
            minItems: 1,
            maxItems: 20,
            items: {
              type: "object",
              properties: {
                kind: {
                  type: "string",
                  enum: ["text", "storyboard", "image", "video"],
                },
                prompt: { type: "string" },
                label: { type: "string" },
              },
              required: ["kind", "prompt"],
              additionalProperties: false,
            },
          },
        },
        required: ["nodes"],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: true },
      execute: (input: Any) => {
        if (
          !Array.isArray(input.nodes) ||
          !input.nodes.length ||
          input.nodes.length > 20
        )
          throw new Error("需要 1–20 个节点");
        if (
          input.nodes.some(
            (n: Any) =>
              !["text", "storyboard", "image", "video"].includes(n.kind) ||
              typeof n.prompt !== "string",
          )
        )
          throw new Error("节点类型或描述无效");
        const nodes = input.nodes.map((n: Any, i: number) => ({
          id: id(),
          type: "media",
          position: {
            x: 80 + i * 340,
            y: 80 + (current.current.doc?.nodes.length || 0) * 30,
          },
          data: {
            kind: n.kind,
            label: n.label || titles[n.kind],
            prompt: n.prompt,
            ...nodeDefaults(n.kind, config.models, system.models, current.current.doc?.generationPolicy),
          },
        }));
        update((d) => ({ ...d, nodes: [...d.nodes, ...nodes] }));
        activateWorkflowStage("canvas");
        return {
          staged_node_ids: nodes.map((n: Any) => n.id),
          generation_submitted: false,
        };
      },
    });
    return () => lifecycle.abort();
  }, [project?.id, update, config.models, system.models]);
  const node = doc?.nodes.find((n) => n.id === selected);
  const data = (node?.data || {}) as Any;
  function pendingInitialStateChecks(targetId: string) {
    return (doc?.edges || [])
      .filter((edge) => edge.target === targetId)
      .map((edge) => doc?.nodes.find((item) => item.id === edge.source))
      .filter(
        (source) =>
          source?.data.kind === "image" &&
          source.data.assetId &&
          requiresInitialStateReview(source.data.prompt) &&
          !source.data.state_reviewed,
      );
  }
  const pendingInitialStateNodes =
    node?.data.kind === "video" ? pendingInitialStateChecks(node.id) : [];
  const activeJob = jobs.find((j) => j.node_id === selected);
  const activeCount = jobs.filter((j) =>
    ["queued", "running"].includes(j.status),
  ).length;
  function editNode(patch: Any) {
    if (!selected) return;
    update((d) => {
      if (!("prompt" in patch)) return patchNode(d, selected, patch);
      const { prompt, ...rest } = patch;
      const next = updateLinkedNodePrompt(d, selected, String(prompt));
      return Object.keys(rest).length ? patchNode(next, selected, rest) : next;
    });
  }
  function changeModel(patch: Any) {
    if (!selected) return;
    if (data.canonicalScriptProjection)
      patch = { ...patch, generationPolicyInherited: false };
    // Keep authored bindings; unsupported combinations are reported before submission.
    update((d) =>
      patchNode(
        d,
        selected,
        patch,
      ),
    );
  }
  function newNode(
    kind: string,
    prompt = "",
    extra: Any = {},
    sourceNodeId?: string,
  ) {
    const nid = id();
    const offset = doc?.nodes.length || 0;
    update((d) => ({
      ...d,
      nodes: [
        ...d.nodes,
        {
          id: nid,
          type: "media",
          position: {
            x: 80 + (offset % 3) * 350,
            y: 80 + Math.floor(offset / 3) * 330,
          },
          data: {
            kind,
            label: titles[kind],
            prompt,
            ...nodeDefaults(kind, config.models, system.models, doc?.generationPolicy),
            ...extra,
          },
        },
      ],
      edges:
        sourceNodeId &&
        d.nodes.some((item) => item.id === sourceNodeId) &&
        !d.edges.some(
          (edge) => edge.source === sourceNodeId && edge.target === nid,
        )
          ? [...d.edges, { id: id(), source: sourceNodeId, target: nid }]
          : d.edges,
    }));
    setSelected(nid);
    setPanel(null);
    return nid;
  }
  function generateStoryboardFromScript(sourceNode: Any) {
    if (!doc || busy) return;
    const existingId = doc.edges.find((edge) => edge.source === sourceNode.id &&
      doc.nodes.some((item) => item.id === edge.target && item.data.kind === "storyboard"))?.target;
    const storyboardId = existingId || newNode(
      "storyboard",
      String(sourceNode.data.text),
      {},
      sourceNode.id,
    );
    if (existingId) {
      const defaults = nodeDefaults("storyboard", config.models, system.models, doc.generationPolicy);
      update((document) => patchNode(document, existingId, {
        model_id: defaults.model_id,
        parameters: defaults.parameters,
        model_capabilities: undefined,
      }));
    }
    setSelected(storyboardId);
    setPendingAutoRunNodeId(storyboardId);
    setNotice(existingId ? "正在使用已有分镜规划节点提交任务" : "已建立并连接分镜规划节点，正在提交任务");
    setTimeout(() => fitView({ nodes: [{ id: storyboardId }], padding: 0.8 }), 80);
  }
  async function promoteCanvasScript(sourceNode: Any) {
    const snapshot = current.current;
    const client = collaboration.current!;
    const generation = client.drafts.generation;
    const body = String(sourceNode?.data?.text || "").trim();
    if (!snapshot.project || !snapshot.doc || sourceNode?.data?.kind !== "text" || !body)
      throw new Error("请先生成或填写剧本正文");
    requireOwnedSaved();
    await save();
    const check = () => {
      if (current.current.project?.id !== snapshot.project!.id || client.drafts.generation !== generation)
        throw new Error("作品已切换，已取消旧页面的剧本提升操作");
      requireOwnedSaved();
      if (dirty.current || saveFlight.current) throw new Error("请先保存当前修改或解决冲突，再提升正式剧本");
    };
    check();
    const node = [...client.rows.values()].find(row => row.kind === 'node' && row.content.node.id === sourceNode.id);
    const graph = [...client.rows.values()].find(row => row.kind === 'graph');
    if (!node || !graph || node.assignee_id !== session.user.id)
      throw new Error("只能提升自己负责且已保存的自由文本节点");
    if (String(node.content.node.data.text||'').trim()!==body)
      throw new Error('节点正文在操作期间已变化，请重新查看后再提升');
    const objectVersion = (row: Any) => ({id:row.id,expected_revision:row.revision,assignment_epoch:row.assignment_epoch});
    const nodeVersion = objectVersion(node), graphVersion = objectVersion(graph);
    const episodeNo = snapshot.project.episode_no || 1;
    const currentScript = await api(`/productions/${snapshot.project.production_id}/episode-scripts/${episodeNo}`);
    check();
    if (currentScript.assignee_id !== session.user.id)
      throw new Error("请先在剧本页分配或明确接管正式剧本，再提升画布正文");
    await api(`/projects/${snapshot.project.id}/script-promotion`,send("POST", {
      node:nodeVersion,graph:graphVersion,
      script_revision:currentScript.revision,script_assignment_epoch:currentScript.assignment_epoch,
    }));
    if (current.current.project?.id !== snapshot.project.id || client.drafts.generation !== generation) return;
    setWorkflowDataRevision((value) => ({ ...value, script: value.script + 1 }));
    if (dirty.current || saveFlight.current || ownedUnsaved()) {
      setNotice("正式剧本已提升；操作期间新增的本地草稿已保留，请处理草稿后刷新查看");
      return;
    }
    await openProject(snapshot.project.id);
    setNotice("画布剧本已保存为本集正式剧本；可进入剧本页继续修订和审核");
  }
  async function captureDirector(blob:Blob,prompt:string,capturedStage:Any) {
    const snapshot=current.current,client=collaboration.current!,generation=client.drafts.generation;
    if(!snapshot.project||!snapshot.doc)throw new Error('请先打开分集');
    const pid=snapshot.project.id,stageSnapshot=JSON.stringify(capturedStage);
    const check=()=>{
      if(current.current.project?.id!==pid||client.drafts.generation!==generation)
        throw new Error('作品已切换，已取消旧页面的截图操作');
      requireOwnedSaved();
      if(JSON.stringify((current.current.doc as Any)?.director||defaultStage())!==stageSnapshot)
        throw new Error('截图期间导演台已改变，请重新截图');
    };
    check();await save();check();
    if(dirty.current||saveFlight.current)throw new Error('请先解决保存冲突再截图');
    const director=[...client.rows.values()].find(row=>row.kind==='director');
    const graph=[...client.rows.values()].find(row=>row.kind==='graph');
    if(!director||!graph||director.assignee_id!==session.user.id)
      throw new Error('请先分配或明确接管导演台，才能建立截图节点');
    const version=(row:Any)=>({id:row.id,expected_revision:row.revision,assignment_epoch:row.assignment_epoch});
    const directorVersion=version(director),graphVersion=version(graph);
    const nid=id(),node={id:nid,type:'media',data:{kind:'image',label:titles.image,prompt,
      ...nodeDefaults('image',config.models,system.models,snapshot.doc.generationPolicy),resolution:'1280x720'}};
    const form=new FormData();form.append('file',blob,'导演构图.png');
    const asset=await api(`/projects/${pid}/assets`,{method:'POST',body:form});
    check();
    if(dirty.current||saveFlight.current)throw new Error('截图已上传为素材；页面有新修改，请保存后重新截图建节点');
    await api(`/projects/${pid}/director-captures`,send('POST',{
      director:directorVersion,graph:graphVersion,asset_id:asset.id,node,
    }));
    if(current.current.project?.id!==pid||client.drafts.generation!==generation)return;
    if(dirty.current||saveFlight.current||ownedUnsaved()){
      setNotice('截图节点已建立；本地新草稿已保留，处理后刷新查看');return;
    }
    await openProject(pid);
    if(current.current.project?.id!==pid)return;
    setSelected(nid);activateWorkflowStage('canvas');
    setNotice('构图已保存为图像节点，完善场景描述后即可生成');
  }
  function startStoryboardPlanning() {
    if (!doc) return;
    if (storyboardSubmissionRef.current || jobs.some((job) =>
      job.kind === "storyboard" && ["queued", "running"].includes(job.status),
    )) {
      setNotice("分镜规划任务已经在队列中，请等待当前任务完成");
      return;
    }
    const scriptNode = doc.nodes.find((node) =>
      node.data?.canonicalScriptProjection && node.data?.scriptStatus === "approved" && String(node.data?.text || "").trim(),
    );
    if (!scriptNode) {
      report(new Error("请先在剧本页批准本集剧本，再开始分镜规划"));
      activateWorkflowStage("script");
      return;
    }
    storyboardSubmissionRef.current = true;
    generateStoryboardFromScript(scriptNode);
  }
  function removeNode() {
    if (!selected) return;
    update((d) => {
      const affected = d.edges
        .filter((e) => e.source === selected)
        .map((e) => e.target);
      return invalidate(
        {
          ...d,
          nodes: d.nodes.filter((n) => n.id !== selected),
          edges: d.edges.filter(
            (e) => e.source !== selected && e.target !== selected,
          ),
        },
        affected,
      );
    });
    setSelected(null);
  }
  async function prepareProjectSwitch() {
    requireOwnedSaved();
    let preservedDraft = false;
    if (dirty.current || saveFlight.current) await save();
    if (dirty.current) {
      if (!conflictRef.current)
        throw new Error("项目尚未保存，请先解决保存失败后再新建项目。");
      const snapshot = current.current;
      if (!snapshot.project || !snapshot.doc)
        throw new Error("当前项目草稿不可用，无法安全切换项目。");
      const backup = JSON.stringify(
        {
          format: "yingxu-project-draft-v1",
          project_id: snapshot.project.id,
          name: snapshot.project.name,
          revision: revision.current,
          production_revision: productionRevision.current,
          document: snapshot.doc,
        },
        null,
        2,
      );
      sessionStorage.setItem("yingxu-conflict-" + snapshot.project.id, backup);
      dirty.current = false;
      conflictRef.current = false;
      setConflict(false);
      setSaved("已保存");
      preservedDraft = true;
    }
    return preservedDraft;
  }
  async function refreshProductionHierarchy() {
    const [productionList, episodeList] = await Promise.all([
      api(`/productions?workspace_id=${encodeURIComponent(activeWorkspaceId)}`),
      api(`/projects?workspace_id=${encodeURIComponent(activeWorkspaceId)}`),
    ]);
    setProductions(productionList);
    setProjects(episodeList);
    return { productions: productionList, projects: episodeList };
  }
  async function switchWorkspace(workspaceId:string) {
    if(workspaceId===activeWorkspaceId)return;
    await prepareProjectSwitch();
    const [productionList,episodeList]=await Promise.all([
      api(`/productions?workspace_id=${encodeURIComponent(workspaceId)}`),
      api(`/projects?workspace_id=${encodeURIComponent(workspaceId)}`),
    ]);
    requireOwnedSaved();
    setActiveWorkspaceId(workspaceId);setProductions(productionList);setProjects(episodeList);
    if(episodeList.length) await openProject(episodeList[0].id);
    else {
      current.current={project:null,doc:null};setProject(null);setDoc(null);setAssets([]);setJobs([]);
      setProjectSetupOpen(false);
    }
  }
  function openProjectSetup() {
    if (!canCreateProduction) {
      setError("只有团队 owner 可以创建作品。");
      return;
    }
    setProjectSetupKey((value) => value + 1);
    setProjectSetupOpen(true);
  }
  async function createProduction(draft: ProjectSetupDraft) {
    const preservedDraft = await prepareProjectSwitch();
    const productionName = draft.name.trim();
    const episode = await api("/projects", send("POST", {...projectSetupPayload(draft),workspace_id:activeWorkspaceId}));
    await refreshProductionHierarchy();
    activateWorkflowStage("overview", "replace");
    await openProject(episode.id);
    setProjectSetupOpen(false);
    setNotice(
      preservedDraft
        ? `已新建“${productionName}”；原集冲突草稿已保存在本浏览器`
        : `已新建作品“${productionName}”并进入 EP01`,
    );
  }
  async function createEpisode(production: ProductionSummary, title: string) {
    await prepareProjectSwitch();
    const episode = await api(
      `/productions/${production.id}/episodes`,
      send("POST", { title }),
    );
    await refreshProductionHierarchy();
    await openProject(episode.id);
    setNotice(`已在“${production.name}”中新建 EP${String(episode.episode_no).padStart(2, "0")}`);
  }
  async function renameProduction(name: string) {
    if (!project) return;
    const target = productions.find((item) => item.id === project.production_id);
    if (!target) throw new Error("当前作品信息尚未载入");
    const trimmed = name.trim();
    if (!trimmed) throw new Error("作品名称不能为空");
    const updated = await api(`/productions/${target.id}`, send("PATCH", {
      revision: productionRevision.current,
      name: trimmed,
    }));
    productionRevision.current = updated.revision;
    setProject((value) => value ? { ...value, production_revision: updated.revision } : value);
    setProductions((items) => items.map((item) => item.id === target.id ? { ...item, ...updated } : item));
    setProductionNameDraft(trimmed);
    setNotice("作品名称已保存");
  }
  async function loadTrash() {
    setTrashItems(await api("/trash"));
  }
  async function openTrash() {
    setPanel("trash");
    await loadTrash();
  }
  function activateGlobalPanel(next: GlobalPanel) {
    const action = planGlobalPanelAction(panel, next);
    if (action.loadTrash) {
      openTrash().catch(report);
      return;
    }
    setPanel(action.panel);
  }
  async function deleteProject(target: Any) {
    if (!target) return;
    if (target.id === project?.id && (dirty.current || saveFlight.current))
      await save();
    if (target.id === project?.id && dirty.current)
      throw new Error("当前项目尚未保存，请先解决保存问题再移入回收站。");
    const entered = window.prompt(
      `项目会移入回收站并可恢复。请输入项目名称“${target.name}”确认：`,
      "",
    );
    if (entered === null) return;
    if (entered.trim() !== target.name)
      throw new Error("项目名称不匹配，未执行删除。");
    await api(`/projects/${target.id}`, send("DELETE"));
    const list = await api("/projects");
    setProjects(list);
    setProductions(await api("/productions"));
    if (target.id === project?.id) {
      dirty.current = false;
      conflictRef.current = false;
      setConflict(false);
      if (list.length) await openProject(list[0].id);
      else {
        current.current = { project: null, doc: null };
        setProject(null);
        setDoc(null);
        setPanel(null);
      }
    }
    await loadTrash();
    setNotice(`项目“${target.name}”已移入回收站`);
  }
  async function deleteAsset(asset: Asset) {
    if (!project) return;
    if (!window.confirm(`将素材“${asset.name}”移入回收站？项目中的引用会暂时不可用，恢复后会重新出现。`)) return;
    await api(`/projects/${project.id}/assets/${asset.id}`, send("DELETE"));
    setAssets((items) => items.filter((item) => item.id !== asset.id));
    await loadTrash();
    setNotice(`素材“${asset.name}”已移入回收站`);
  }
  async function restoreTrashItem(kind: "project" | "asset" | "source" | "chapter", item: Any) {
    const currentProjectId = project?.id;
    await api(`/trash/${kind}/${item.id}/restore`, send("POST"));
    setProjects(await api("/projects"));
    setProductions(await api("/productions"));
    if (kind === "asset" && currentProjectId && item.production_id === project?.production_id)
      await refresh(currentProjectId);
    if (kind === "source" || kind === "chapter") setWorkflowDataRevision((value) => ({ ...value, source: value.source + 1, adaptation: value.adaptation + 1 }));
    await loadTrash();
    const label = kind === "project" ? "项目" : kind === "asset" ? "素材" : kind === "source" ? "原著" : "章节";
    setNotice(`${label}“${item.name}”已恢复`);
  }
  function sourceAssets(nid: string) {
    const sources =
      doc?.edges
        .filter((e) => e.target === nid)
        .map((e) => doc.nodes.find((n) => n.id === e.source)?.data.assetId)
        .filter(Boolean) || [];
    return [
      ...new Set([
        ...sources,
        ...((doc?.nodes.find((n) => n.id === nid)?.data
          .asset_ids as string[]) || []),
      ]),
    ];
  }
  function storyboardContextId(document: Doc) {
    return [...document.nodes]
      .reverse()
      .find(
        (item) => item.data.kind === "storyboard" && Boolean(item.data.text),
      )?.id;
  }
  function setSingleFirstFrame(assetId: string, providerName: string) {
    if (!selected) return;
    update((d) => setSingleImageReference(d, selected, assetId));
    setNotice(
      assetId
        ? `已将 ${providerName} 首帧限定为所选素材`
        : `已清除 ${providerName} 的图像首帧引用`,
    );
  }
  async function run(n = node) {
    if (!n || !project || busy) return;
    setBusy(true);
    setError("");
    try {
      if (n.data.kind === "video") {
        const pendingChecks = pendingInitialStateChecks(n.id);
        if (pendingChecks.length) {
          const names = pendingChecks
            .map((item) => item?.data.label || "关联分镜图")
            .join("、");
          throw new Error(`请先核验「${names}」的首帧状态，再生成视频。`);
        }
      }
      await save();
      if (dirty.current) throw new Error("项目尚未保存，请先解决保存冲突");
      const targetProvider = config.models.find(
        (provider: Any) => provider.id === n.data.model_id,
      );
      if (!targetProvider || n.data.model_id === "local")
        throw new Error("该节点未配置外部 Provider；系统不会自动回退到其他模型");
      const input = {
        ...n.data,
        model_id: n.data.model_id,
        asset_ids: sourceAssets(n.id),
        parameters: {...targetProvider.defaults,...(n.data.parameters as Any || {})},
        prompt: String(n.data.prompt || ""),
        target_duration:
          n.data.kind === "text" || n.data.kind === "storyboard"
            ? n.data.target_duration || doc?.duration
            : undefined,
        film_bible:
          n.data.kind === "storyboard"
            ? n.data.film_bible !== false
            : undefined,
      };
      await api(
        `/projects/${project.id}/jobs`,
        send("POST", {
          node_id: n.id,
          kind: n.data.kind,
          submission_id: id(),
          input,
        }),
      );
      await refresh(project.id);
      setNotice("任务已进入服务器队列，关闭页面也会继续执行");
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function runGraph(options: Any = {}) {
    if (!project || busy) return;
    setBusy(true);
    try {
      await save();
      if (dirty.current) throw new Error("请先解决保存冲突再执行画布");
      const result = await api(
        `/projects/${project.id}/run`,
        send("POST", { submission_id: id(), ...options }),
      );
      await refresh(project.id);
      setPanel("jobs");
      setNotice(`${result.count} 个任务已按连线依赖加入队列`);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  function adoptShots(job: Job) {
    if (!job.result?.shots) return;
    setPanel("jobs");
    setNotice("请在任务中心比较分镜候选及影响范围后明确采纳；不会在本地覆盖整份分镜表。");
  }
  function shotNodes(shot: Any, _index: number) {
    update((d) =>
      ensureShotNodes(
        d,
        config.models,
        system.models,
        id,
        [shot.id],
        shot.storyboardNode || storyboardContextId(d),
      ),
    );
    activateWorkflowStage("canvas");
    setSelected(null);
    setTimeout(() => fitView({ padding: 0.2 }), 80);
  }
  function appendShotTimeline() {
    if (!doc) return;
    const plan = planShotTimeline(doc.shots, doc.nodes, assets, id);
    if (plan.issues.length) {
      report(new Error(plan.issues.join("；")));
      return;
    }
    update((d) => ({ ...d, timeline: [...d.timeline, ...plan.clips] }));
    setTimelineOpen(true);
    setNotice(`已按分镜顺序追加 ${plan.clips.length} 个镜头，保留原时间线`);
  }
  function allShotNodes() {
    update((d) =>
      ensureShotNodes(
        d,
        config.models,
        system.models,
        id,
        undefined,
        storyboardContextId(d),
      ),
    );
    activateWorkflowStage("canvas");
    setSelected(null);
    setTimeout(() => fitView({ padding: 0.2 }), 80);
    setNotice("已补齐分镜生成节点，检查提示词后可运行画布");
  }
  async function generateStoryboardImages(shotUids: string[]) {
    const snapshot = current.current;
    if (!snapshot.project || !snapshot.doc || busy) return;
    const selected = new Set(shotUids);
    const targetShots = snapshot.doc.shots.filter((shot) =>
      selected.has(shotIdentity(shot)),
    );
    if (!targetShots.length) throw new Error("请先选择需要生成的镜头");
    const visual = visualBibleOf(snapshot.doc);
    const hasVisualCards = Object.values(visual.cards).some((card) => !card.deletedAt && card.status !== "deprecated");
    for (const shot of targetShots) {
      const bindings = shot.assetBindings || {};
      const versionIds = [
        ...(bindings.characters || []).map((item: Any) => item.versionId),
        ...(bindings.props || []).map((item: Any) => item.versionId),
        bindings.scene?.versionId,
      ].filter(Boolean);
      if (hasVisualCards && !versionIds.length)
        throw new Error("所选镜头尚未绑定视觉版本，请先在“分镜规划”确认角色、场景或道具");
      for (const versionId of versionIds) {
        const version = visual.versions[versionId];
        if (!version || version.status !== "locked")
          throw new Error("所选镜头引用的视觉版本尚未锁定，请先到“塑角造景”确认");
        if (!version.references?.some((item: Any) => item.role === "primary" && item.assetId))
          throw new Error("所选镜头引用的视觉版本缺少主参考图，请先到“塑角造景”生成或上传");
      }
    }
    let prepared = deriveManagedGraph(
      ensureShotNodes(
        snapshot.doc,
        config.models,
        system.models,
        id,
        targetShots.map((shot) => shot.id),
        storyboardContextId(snapshot.doc),
      ),
    ) as Doc;
    const nodeIds = selectedShotImageNodeIds(prepared, shotUids);
    if (nodeIds.length !== targetShots.length)
      throw new Error("部分镜头缺少分镜图生成节点");
    for (const nodeId of nodeIds) {
      const imageNode = prepared.nodes.find((item) => item.id === nodeId);
      if (!String(imageNode?.data?.prompt || "").trim())
        throw new Error("所选镜头存在空的 Image Prompt，请先填写后再生成");
      const provider = config.models.find(
        (item: Any) => item.id === imageNode?.data?.model_id,
      );
      if (!provider || imageNode?.data?.model_id === "local")
        throw new Error("所选镜头尚未选择可用的图片生成服务");
    }
    current.current = { project: snapshot.project, doc: prepared };
    setDoc(prepared);
    dirty.current = true;
    setSaved("未保存");
    setBusy(true);
    setError("");
    try {
      await save();
      if (dirty.current) throw new Error("请先解决保存冲突再生成分镜图");
      const result = await api(
        `/projects/${snapshot.project.id}/run`,
        send("POST", {
          submission_id: id(),
          node_ids: nodeIds,
          exact: true,
        }),
      );
      await refresh(snapshot.project.id);
      setNotice(`已提交 ${result.count} 个所选分镜图任务`);
    } catch (reason) {
      report(reason);
      throw reason;
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!pendingAutoRunNodeId) return;
    const target = doc?.nodes.find((item) => item.id === pendingAutoRunNodeId);
    if (!target) return;
    setPendingAutoRunNodeId(null);
    void run(target).finally(() => { storyboardSubmissionRef.current = false; });
  }, [pendingAutoRunNodeId, doc?.nodes]);
  async function generateShotVideos(shotUids: string[]) {
    const snapshot = current.current;
    if (!snapshot.project || !snapshot.doc || busy) return;
    const selectedUids = new Set(shotUids);
    const targetShots = snapshot.doc.shots.filter((shot) =>
      selectedUids.has(shotIdentity(shot)),
    );
    if (!targetShots.length) throw new Error("请先选择需要生成的视频镜头");
    let prepared = deriveManagedGraph(
      ensureShotNodes(
        snapshot.doc,
        config.models,
        system.models,
        id,
        targetShots.map((shot) => shot.id),
        storyboardContextId(snapshot.doc),
      ),
    ) as Doc;
    const rows = deriveVideoProductionRows(prepared, assets, jobs, config.models);
    const targets = validateVideoSubmission(rows, shotUids);
    let extendedCount = 0;
    for (const target of targets) {
      if ((target.shot.videoReferenceMode||(snapshot.doc as Any).videoReferenceMode)!=='multimodal'&&target.effectiveDuration > target.plannedDuration) {
        prepared = updateShot(prepared, target.shot.id, { duration: target.effectiveDuration }) as Doc;
        extendedCount += 1;
      }
    }
    const nodeIds = selectedShotVideoNodeIds(prepared, shotUids);
    if (nodeIds.length !== targets.length)
      throw new Error("部分镜头缺少视频生成节点");
    current.current = { project: snapshot.project, doc: prepared };
    setDoc(prepared);
    dirty.current = true;
    setSaved("未保存");
    setBusy(true);
    setError("");
    try {
      await save();
      if (dirty.current) throw new Error("请先解决保存冲突再生成视频");
      const result = await api(
        `/projects/${snapshot.project.id}/run`,
        send("POST", {
          submission_id: id(),
          node_ids: nodeIds,
          exact: true,
        }),
      );
      await refresh(snapshot.project.id);
      setPanel("jobs");
      setNotice(`已提交 ${result.count} 个所选视频任务${extendedCount ? `；${extendedCount} 个镜头已按对白自动延长` : ""}`);
    } catch (reason) {
      report(reason);
      throw reason;
    } finally {
      setBusy(false);
    }
  }
  async function uploadFiles(files: FileList | null, category = uploadCategory) {
    if (!files || !project) return;
    setBusy(true);
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        await api(`/projects/${project.id}/assets?category=${encodeURIComponent(category)}`, {
          method: "POST",
          body: form,
        });
      }
      await refresh(project.id);
      setPanel("assets");
      setNotice("素材已保存到主机，可在其他电脑访问");
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function uploadVisualReference(versionId: string, file: File) {
    const snapshot = current.current;
    if (!snapshot.project || !snapshot.doc) return;
    const visual = visualBibleOf(snapshot.doc);
    const version = visual.versions[versionId];
    const card = version ? visual.cards[version.cardId] : undefined;
    if (!version || !card) throw new Error("视觉版本不存在");
    const form = new FormData();
    form.append("file", file);
    const asset = await api(
      `/projects/${snapshot.project.id}/assets?category=${encodeURIComponent(visualAssetCategory(card))}`,
      { method: "POST", body: form },
    );
    if (asset.kind !== "image") throw new Error("主参考素材必须是图片");
    update((document) =>
      attachUploadedPrimaryReference(document, versionId, asset),
    );
    setAssets((items) => [
      asset,
      ...items.filter((item) => item.id !== asset.id),
    ]);
    setNotice("主参考图已上传，请检查画面后确认锁定");
  }
  async function generateVisualReference(versionId: string) {
    const snapshot = current.current;
    if (!snapshot.project || !snapshot.doc) return;
    const generation = collaboration.current!.drafts.generation;
    const visual = visualBibleOf(snapshot.doc);
    const version = visual.versions[versionId];
    const card = version ? visual.cards[version.cardId] : undefined;
    if (!version || !card) throw new Error("视觉版本不存在");
    const alreadyActive = jobs.find((job) =>
      job.node_id === `visual-version:${versionId}` && ["queued", "running"].includes(job.status),
    );
    if (alreadyActive) throw new Error("该资产参考图已在排队或生成中，请勿重复提交");
    const target = resolveVisualGenerationTarget(
      card,
      snapshot.doc.generationPolicy,
      config.models,
      system.models,
    );
    const provider = config.models.find(
      (item: Any) => item.id === target.model_id,
    );
    if (!provider) throw new Error("图片生成服务已不存在，请重新选择");
    let capabilities: Any | undefined;
    if (isStateCard(card)) {
      const catalog = await api(
        "/models",
      );
      const model = (catalog.models || []).find(
        (item: Any) => item.id === target.model_id,
      );
      capabilities = model?.capabilities;
    }
    const plan = planVisualReferenceGeneration(
      snapshot.doc,
      versionId,
      target,
      capabilities,
    );
    if (current.current.project?.id !== snapshot.project.id || collaboration.current!.drafts.generation !== generation)
      throw new Error("作品已切换，请从当前作品重新提交");
    await save();
    if (current.current.project?.id !== snapshot.project.id || collaboration.current!.drafts.generation !== generation)
      throw new Error("作品已切换，请从当前作品重新提交");
    if (dirty.current) throw new Error("项目尚未保存，请先解决保存冲突");
    const submissionId = id();
    const job = await api(
      `/projects/${snapshot.project.id}/jobs`,
      send("POST", {
        node_id: `visual-version:${versionId}`,
        kind: "image",
        submission_id: submissionId,
        input: {
          model_id: plan.model_id,
          prompt: plan.prompt,
          asset_ids: plan.assetIds,
          asset_category: plan.assetCategory,
          output_name: `${card.name} · ${isStateCard(card) ? "状态参考图" : "主参考图"} · V${version.version}.png`,
          parameters: {...provider.defaults},
          visual_reference: {
            versionId,
            targetSource: plan.targetSource,
            parentVersionId: plan.parentVersionId,
            parentReferenceAssetId: plan.parentReferenceAssetId,
          },
        },
      }),
    );
    if (!job.collaboration?.target) throw new Error("服务端未返回生成目标快照");
    if (current.current.project?.id !== snapshot.project.id) return;
    await refresh(snapshot.project.id);
    setNotice("主参考图任务已进入队列；完成后在任务中心比较并采纳，再人工确认锁定");
  }
  async function runSmartBatch(kind: BatchGenerationKind) {
    const snapshot = current.current;
    if (!snapshot.project || !snapshot.doc || busy) return;
    const plan = planBatchGeneration(
      snapshot.doc,
      jobs,
      config.models,
      system.models,
      kind,
    );
    const names = {
      assets: "资产参考图",
      shot_images: "分镜图",
      shot_videos: "视频",
    };
    if (!plan.readyIds.length) {
      const detail = plan.blocked.slice(0, 3).map((item) => `${item.label}：${item.reason}`).join("；");
      report(new Error(detail || `没有需要生成的${names[kind]}`));
      return;
    }
    setBusy(true);
    setError("");
    try {
      let submitted = 0;
      const failed: string[] = [];
      if (kind === "assets") {
        for (const versionId of plan.readyIds) {
          try {
            await generateVisualReference(versionId);
            submitted += 1;
          } catch (reason: any) {
            failed.push(reason?.message || String(reason));
          }
        }
      } else {
        await save();
        if (dirty.current) throw new Error("请先解决保存冲突再批量生成");
        const result = await api(
          `/projects/${snapshot.project.id}/run`,
          send("POST", {
            submission_id: id(),
            node_ids: plan.readyIds,
            exact: true,
          }),
        );
        submitted = result.count;
        await refresh(snapshot.project.id);
      }
      if (!submitted && failed.length) throw new Error(failed[0]);
      if (kind === "shot_videos") setPanel("jobs");
      setNotice(
        `已提交 ${submitted} 个${names[kind]}任务` +
          (plan.blocked.length ? `，${plan.blocked.length} 项条件未满足` : "") +
          (plan.skipped.length ? `，跳过 ${plan.skipped.length} 项` : "") +
          (failed.length ? `，${failed.length} 项提交失败` : ""),
      );
      if (failed.length) setError(`部分任务提交失败：${failed[0]}`);
      else if (plan.blocked.length) {
        const details = plan.blocked
          .slice(0, 3)
          .map((item) => `${item.label}：${item.reason}`)
          .join("；");
        setError(`${plan.blocked.length} 项未提交：${details}`);
      }
    } catch (reason) {
      report(reason);
    } finally {
      setBusy(false);
    }
  }
  async function changeAssetCategory(asset: Asset, category: string) {
    if (!project) return;
    try {
      const updated = await api(`/projects/${project.id}/assets/${asset.id}`, send("PATCH", { category }));
      setAssets((items) => items.map((item) => item.id === asset.id ? { ...item, ...updated } : item));
      setNotice(`已归类为${assetCategories[category]}`);
    } catch (e) { report(e); }
  }
  function addTimeline(asset: Asset) {
    update((d) => ({
      ...d,
      timeline: [
        ...d.timeline,
        {
          id: id(),
          asset_id: asset.id,
          start: 0,
          duration: asset.kind === "video" ? asset.metadata?.duration || 5 : 5,
          volume: 1,
        },
      ],
    }));
    setTimelineOpen(true);
    setNotice("已加入时间线");
  }
  async function exportFilm(
    source: "legacy" | "editor",
    editorOverride?: EditorDocument["timeline"],
  ) {
    if (!project || !doc) return;
    try {
      const editorTimeline = source === "editor"
        ? editorOverride || doc.editor?.timeline
        : undefined;
      if (source === "editor" && !editorTimeline?.tracks?.some((track) => track.elements?.length)) {
        throw new Error("高级剪辑中还没有可导出的轨道内容");
      }
      if (source === "legacy" && !doc.timeline.length) {
        throw new Error("时间线预览中还没有可导出的镜头");
      }
      await save();
      if (dirty.current) throw new Error("项目尚未保存，请先解决保存冲突");
      await api(
        `/projects/${project.id}/jobs`,
        send("POST", {
          node_id: "export",
          kind: "export",
          submission_id: id(),
          input: {
            timeline: doc.timeline,
            editor_timeline: source === "editor" ? editorTimeline : undefined,
            render_mode: source,
            resolution: (doc as any).export_resolution || "1280x720",
            audio_id: (doc as any).audio_id,
            subtitle_id: (doc as any).subtitle_id,
            music_volume: (doc as any).music_volume ?? 0.3,
            transition: (doc as any).transition || "cut",
          },
        }),
      );
      setPanel("jobs");
      await refresh(project.id);
    } catch (e) {
      report(e);
    }
  }
  async function history() {
    if (!project) return;
    setRevisions(await api(`/projects/${project.id}/revisions`));
    setPanel("history");
  }
  const renderedNodes =
    doc?.nodes.map((n) => {
      // React Flow hides a node until it knows its dimensions. Keep those
      // measurements outside the persisted document so asset/job refreshes do
      // not reset every node to `visibility: hidden`.
      const measured = nodeMeasurements.current.get(n.id);
      if (isManagedVisualNode(n as Any))
        return {
          ...n,
          width: n.width ?? measured?.width,
          height: n.height ?? measured?.height,
          selected: n.id === selected,
        };
      return {
        ...n,
        width: n.width ?? measured?.width,
        height: n.height ?? measured?.height,
        selected: n.id === selected,
        data: {
          ...n.data,
          asset: assets.find((a) => a.id === n.data.assetId),
          job: jobs.find((j) => j.node_id === n.id),
          mediaRetryKey,
          layoutVersion,
          onMediaFailure: reportMediaFailure,
          onMediaReady: clearMediaFailure,
        },
      };
    }) || [];
  const renderedEdges =
    doc?.edges.map((edge, edgeIndex) => {
      const managed =
        edge.data?.managed === true && edge.data?.origin === "visual_binding";
      const stroke = managed ? "#d4a963" : "#718991";
      const focusedNode = hoveredNode || selected;
      const related =
        !focusedNode || edge.source === focusedNode || edge.target === focusedNode;
      return {
        ...edge,
        // Orthogonal smooth-step edges share vertical trunks when one source
        // fans out to many shots. Bezier wires diverge immediately, matching
        // the readable socket-to-socket routing used by node editors.
        type: "default",
        pathOptions: {
          curvature: managed
            ? 0.34 + (edgeIndex % 3) * 0.035
            : 0.25 + (edgeIndex % 3) * 0.025,
        },
        animated: edge.animated !== false && related,
        className: `${edge.className || ""} mvc-flow-edge${managed ? " mvc-flow-edge-managed" : ""}`.trim(),
        zIndex: 0,
        markerEnd:
          edge.markerEnd || {
            type: MarkerType.ArrowClosed,
            color: stroke,
            width: 13,
            height: 13,
          },
        style: {
          stroke,
          strokeWidth: focusedNode && related ? 2.6 : managed ? 1.65 : 1.5,
          opacity: focusedNode
            ? related
              ? 0.96
              : 0.055
            : managed
              ? 0.32
              : 0.38,
          ...edge.style,
        },
      };
    }) || [];
  if (!doc || !project)
    return (
      <div className={booted ? "empty-workspace" : "loading"}>
        {!booted ? <><LoaderCircle className="spin" />{error || "正在打开工作室"}</> : <>
          <AnYingMark size={64}/>
          <span className="eyebrow">ANYING STUDIO</span>
          <select className="team-switcher" aria-label="切换团队" value={activeWorkspaceId} onChange={(e)=>void switchWorkspace(e.target.value).catch(report)}>
            {session.workspaces.map((workspace:Any)=><option key={workspace.id} value={workspace.id}>{workspace.name} · {workspace.role}</option>)}
          </select>
          <h1>{canCreateProduction ? "创建第一部作品" : "尚未加入作品"}</h1>
          <p>{canCreateProduction ? "先确认视觉风格、画幅、目标时长、默认模型与 Project Bible，再进入 EP01。" : "你已加入团队，但还没有获权作品。请联系团队 owner 将你加入作品。"}</p>
          {canCreateProduction && <button className="primary" onClick={openProjectSetup}><Plus size={17}/>创建第一部作品</button>}
          <div className="account-actions"><a href="/members">成员管理</a>{session.user?.platform_role==='platform_admin'&&<a href="/admin">平台管理</a>}<button className="quiet" onClick={async()=>{await api('/auth/logout',send('POST'));onLogout();}}>退出登录</button></div>
          {error && <div className="error">{error}</div>}
        </>}
        {canCreateProduction && projectSetupOpen && <ProjectSetupDialog
          key={projectSetupKey}
          providers={config.models}
          localModels={system.models}
          onClose={projects.length ? () => setProjectSetupOpen(false) : undefined}
          onCreate={createProduction}
        />}
      </div>
    );
  const assetBatchPlan = planBatchGeneration(
    doc, jobs, config.models, system.models, "assets",
  );
  const imageBatchPlan = planBatchGeneration(
    doc, jobs, config.models, system.models, "shot_images",
  );
  const videoBatchPlan = planBatchGeneration(
    doc, jobs, config.models, system.models, "shot_videos",
  );
  const persistedEditorTimeline = doc.editor?.timeline;
  const exportEditorTimeline = editorExportTimeline || persistedEditorTimeline;
  const exportEditorTracks = exportEditorTimeline?.tracks || [];
  const currentProduction =
    productions.find((item) => item.id === project.production_id) || null;
  const currentEpisodes = episodesForProduction(projects, project.production_id);
  const currentWorkflowScope = workflowStageScope(workflowStage);
  const workflowGuide = deriveWorkflowGuide({
    adaptation: workflowContext.adaptation,
    scripts: workflowContext.scripts,
    currentProject: project,
    document: doc,
    jobs,
  });
  const projectBibleFields = bibleFields(doc);
  const filmBiblePanelProps: React.ComponentProps<typeof FilmBiblePanel> = {
    visual: visualBibleOf(doc),
    shots: doc.shots,
    assets,
    jobs,
    generationPolicy: doc.generationPolicy,
    providers: config.models,
    localModels: system.models,
    request: api,
    voiceProfiles: voiceProfilesOf(doc),
    onAdmitVoice:async(value)=>{
      const generation=collaboration.current!.drafts.generation;
      let aid:string;
      if(typeof value==='string')aid=value;
      else{const form=new FormData();form.append('file',value);
        const uploaded=await api(`/projects/${project.id}/assets?category=voice&voice_reference=true`,{method:'POST',body:form});aid=uploaded.id;}
      if(current.current.project?.id!==project.id||collaboration.current!.drafts.generation!==generation)throw new Error('作品已切换，已上传素材保留，请在原作品重新选择');
      const asset=await api(`/projects/${project.id}/assets/${aid}/voice-reference`,send('POST',{authorized:true}));
      if(current.current.project?.id!==project.id||collaboration.current!.drafts.generation!==generation)throw new Error('作品已切换，声音素材保留，未修改角色');
      setAssets(items=>[asset,...items.filter(item=>item.id!==asset.id)]);
      setNotice('声音样本已校验；请保存声音草稿、试听后明确锁定');return asset;
    },
    onChooseVoiceVersion:(cardId,version)=>{
      try{update(document=>chooseVoiceVersion(document,cardId,version));setNotice('音色选择已更新，请保存；相关旧视频将标为待更新')}catch(reason){report(reason)}
    },
    onPreviewAsset: (asset) => setPreview(asset as Asset),
    onSaveVoice: (cardId, profile) => {
      try {
        update((document)=>saveVoiceProfile(document,cardId,profile));
        setNotice("角色声音设定已保存");
      } catch (reason) { report(reason); }
    },
    onGenerateVoice: async (cardId, profile) => {
      requireTtsVoice(profile);
      const generation = collaboration.current!.drafts.generation;
      const card = visualBibleOf(doc).cards[cardId];
      if (!card) throw new Error("角色资产卡不存在");
      const next = saveVoiceProfile(doc, cardId, profile);
      const savedProfile = voiceProfilesOf(next)[cardId];
      update(()=>next);
      await save();
      if (current.current.project?.id !== project.id || collaboration.current!.drafts.generation !== generation)
        throw new Error("作品已切换，请从当前作品重新提交");
      if (dirty.current) throw new Error("角色声音设定尚未保存，请先解决保存冲突");
      const job = await api(`/projects/${project.id}/jobs`, send("POST", {
        node_id: `voice-profile:${cardId}`,
        kind: "audio",
        submission_id: id(),
        input: {
          prompt: savedProfile.previewText,
          model_id: savedProfile.model_id,
          voice_type: savedProfile.voiceType,
          voice_version: savedProfile.version,
          character_name: card.name,
          output_name: `${card.name} · 声音 V${savedProfile.version} 试听.mp3`,
          asset_category: "voice",
          parameters: voiceParameters(config.models,savedProfile),
          voice_profile: { cardId, version: savedProfile.version },
        },
      }));
      if (!job.collaboration?.target) throw new Error("服务端未返回音色目标快照");
      if (current.current.project?.id !== project.id) return;
      await refresh(project.id);
      setNotice("角色音色试听已进入队列；完成后在任务中心比较并采纳");
    },
    onLockVoice: (cardId, locked) => {
      try {
        update((document)=>setVoiceLocked(document,cardId,locked));
        setNotice(locked ? "角色主音色已锁定" : "已创建可编辑的新声音版本");
      } catch (reason) { report(reason); }
    },
    onGenerateCharacterDialogue: async (cardId) => {
      const profile = resolvedVoice(doc,{}, {characterCardId:cardId}).profile as VoiceProfile;
      requireTtsVoice(profile);
      const card = visualBibleOf(doc).cards[cardId];
      if (!profile || profile.status !== "locked") throw new Error("请先试听并锁定角色主音色");
      const dialogues = doc.shots.flatMap((shot) =>
        (Array.isArray(shot.dialogues) ? shot.dialogues : [])
          .filter((dialogue: Any) => voiceCardId(doc,shot,dialogue) === cardId)
          .map((dialogue: Any, index: number) => ({ shot, dialogue, index })),
      );
      if (!dialogues.length) throw new Error("本集分镜没有该角色的结构化对白；重新生成分镜规划后会自动提取对白");
      const existing = new Set(dialogues.filter(({dialogue})=>dialogue.audioVoiceVersion===profile.version
        && assets.some(asset=>asset.id===dialogue.audioAssetId&&asset.kind==='audio'
          &&asset.metadata?.input?.dialogue?.text===dialogue.text
          &&(asset.metadata?.input?.dialogue?.voiceCardId||dialogue.characterCardId)===cardId)).map(({dialogue})=>dialogue.id));
      const pending = new Set(dialogues.filter(({dialogue})=>jobs.some(job=>job.input?.dialogue?.id===dialogue.id
        &&job.input.dialogue.text===dialogue.text&&job.input.dialogue.voiceVersion===profile.version
        &&(job.input.dialogue.voiceCardId||dialogue.characterCardId)===cardId
        &&["queued","running","succeeded"].includes(job.status))).map(({dialogue})=>dialogue.id));
      const needed = dialogues.filter(({dialogue})=>!existing.has(dialogue.id) && !pending.has(dialogue.id));
      if (!needed.length) throw new Error("该角色本集对白已采纳、正在生成或有待采纳候选；请查看任务中心");
      await save();
      if (dirty.current) throw new Error("镜头或音色尚未保存，请先解决保存冲突");
      const audioJobs=needed.map(({shot,dialogue,index})=>{
        const performance = dialoguePerformance(shot, dialogue, profile);
        return {
        node_id:`dialogue:${dialogue.id}`,
        kind:"audio",
        submission_id:id(),
        input:{
          prompt:dialogue.text,
          model_id:profile.model_id,
          voice_type:profile.voiceType,
          voice_version:profile.version,
          character_name:card?.name || dialogue.characterName,
          output_name:`${shot.id || "分镜"} · ${card?.name || "角色"}对白 ${index+1}.mp3`,
          asset_category:"voice",
          parameters:voiceParameters(config.models,profile,performance),
          dialogue:{id:dialogue.id,shotUid:String(shot.uid||shot.id),characterCardId:dialogue.characterCardId,voiceCardId:cardId,voiceVersion:profile.version,text:dialogue.text,emotion:performance.emotion,contextTexts:performance.contextTexts},
        },
      };
      });
      await api(`/projects/${project.id}/audio-jobs`,send("POST",{jobs:audioJobs}));
      await refresh(project.id);
      setNotice(`已批量提交 ${needed.length} 条${card?.name || "角色"}对白`);
      return needed.length;
    },
    onRegenerateDialogue: async (cardId, dialogueId) => {
      const profile = resolvedVoice(doc,{}, {characterCardId:cardId}).profile as VoiceProfile;
      requireTtsVoice(profile);
      const card = visualBibleOf(doc).cards[cardId];
      if (!profile || profile.status !== "locked") throw new Error("请先试听并锁定角色主音色");
      const match = doc.shots.flatMap((shot) =>
        (Array.isArray(shot.dialogues) ? shot.dialogues : [])
          .filter((dialogue: Any) => voiceCardId(doc,shot,dialogue) === cardId && dialogue.id === dialogueId)
          .map((dialogue: Any) => ({ shot, dialogue })),
      )[0];
      if (!match) throw new Error("该对白已不存在，请刷新后重试");
      const active = jobs.some((job) => job.input?.dialogue?.id === dialogueId && job.input?.dialogue?.voiceVersion === profile.version && ["queued","running"].includes(job.status));
      if (active) throw new Error("该对白正在生成，请等待当前任务完成");
      await save();
      if (dirty.current) throw new Error("角色声音设定尚未保存，请先解决保存冲突");
      const performance = dialoguePerformance(match.shot, match.dialogue, profile);
      await api(`/projects/${project.id}/jobs`,send("POST",{
        node_id:`dialogue:${dialogueId}`,
        kind:"audio",
        submission_id:id(),
        input:{
          prompt:match.dialogue.text,
          model_id:profile.model_id,
          voice_type:profile.voiceType,
          voice_version:profile.version,
          character_name:card?.name || match.dialogue.characterName,
          output_name:`${match.shot.id || "分镜"} · ${card?.name || "角色"}对白 · 新版本.mp3`,
          asset_category:"voice",
          parameters:voiceParameters(config.models,profile,performance),
          dialogue:{id:dialogueId,shotUid:String(match.shot.uid||match.shot.id),characterCardId:match.dialogue.characterCardId,voiceCardId:cardId,voiceVersion:profile.version,text:match.dialogue.text,emotion:performance.emotion,contextTexts:performance.contextTexts},
        },
      }));
      await refresh(project.id);
      setNotice("对白已重新提交，旧音频仍保留在素材库");
    },
    focusVersionId: visualFocus,
    onFocusVersion: setVisualFocus,
    onRenameCard: (cardId, name) => {
      try {
        update(() => renameVisualCard(doc, cardId, name));
        setNotice("视觉卡名称已保存");
      } catch (reason) { report(reason); }
    },
    onDeleteCard: (cardId) => {
      const card = visualBibleOf(doc).cards[cardId];
      if (!card || !window.confirm(`将视觉资产卡“${card.name}”移入回收站？恢复后原分镜绑定会重新生效。`)) return;
      try {
        update((currentDoc) => softDeleteVisualCard(currentDoc, cardId));
        setNotice(`视觉资产卡“${card.name}”已移入回收站`);
      } catch (reason) { report(reason); }
    },
    onSaveVersion: (versionId, draft) => {
      try {
        update(() => updateDraftVisualVersion(doc, versionId, {
          spec: { description: draft.description, attributes: draft.attributes },
          invariants: draft.invariants,
        }));
        setNotice("视觉版本文字已保存");
      } catch (reason) { report(reason); }
    },
    onStatus: (versionId, status) => {
      try { update(() => setVisualVersionStatus(doc, versionId, status)); }
      catch (reason) { report(reason); }
    },
    onSetImageOverride: (cardId, override) => {
      try {
        update((document) => setVisualCardImageOverride(document, cardId, override));
        setNotice(override.mode === "override" ? "此资产将使用自定义图片模型" : "此资产将继承项目默认图片模型");
      } catch (reason) { report(reason); }
    },
    onUploadReference: uploadVisualReference,
    onGenerateReference: generateVisualReference,
    onLock: (versionId) => {
      try {
        update((document) => lockVisualVersion(document, versionId));
        setNotice("视觉版本已确认锁定");
      } catch (reason) { report(reason); }
    },
    onFork: (versionId, draft) => {
      try {
        const next = forkLockedVisualVersion(doc, versionId, {
          spec: { description: draft.description, attributes: draft.attributes },
          invariants: draft.invariants,
        });
        update(() => next);
        const source = visualBibleOf(doc).versions[versionId];
        setVisualFocus(visualBibleOf(next).cards[source.cardId].currentVersionId);
        setNotice("已派生新草稿版本；旧版本和分镜绑定保持不变");
      } catch (reason) { report(reason); }
    },
    onUpgrade: (cardId, targetVersionId, scope) => {
      try {
        update(() => upgradeVisualBindings(doc, cardId, targetVersionId, scope));
        setNotice("已升级明确范围内的分镜；旧生成素材已保留并标记待更新");
      } catch (reason) { report(reason); }
    },
    onBind: (shotUid, versionId) => {
      try {
        update(() => bindVisualVersion(doc, shotUid, versionId));
        setNotice("视觉版本已绑定到分镜");
      } catch (reason) { report(reason); }
    },
    onUnbind: (shotUid, versionId) => {
      try {
        update(() => unbindVisualVersion(doc, shotUid, versionId));
        setNotice("视觉版本已从分镜解除");
      } catch (reason) { report(reason); }
    },
    onLocate: (versionId) => {
      const visualNode = doc.nodes.find((item) => item.data?.visualVersionId === versionId);
      if (!visualNode) return;
      activateWorkflowStage("canvas");
      setSelected(visualNode.id);
      setPanel(null);
      setTimeout(() => fitView({ nodes: [{ id: visualNode.id }], padding: 0.8 }), 50);
    },
  };
  const toggleTimelineWorkspace = () => {
    if (view === "editor") {
      setView("canvas");
      setTimelineOpen(true);
      return;
    }
    setTimelineOpen(!timelineOpen);
  };
  return (
    <div className="studio-shell">
      {canCreateProduction && projectSetupOpen && <ProjectSetupDialog
        key={projectSetupKey}
        providers={config.models}
        localModels={system.models}
        onClose={() => setProjectSetupOpen(false)}
        onCreate={createProduction}
      />}
      {previewTimeline && (
        <TimelinePreview
          clips={doc.timeline}
          assets={assets}
          audioId={(doc as any).audio_id}
          musicVolume={(doc as any).music_volume ?? 0.3}
          transition={(doc as any).transition || "cut"}
          ratio={doc.ratio || "16:9"}
          autoPlay
          onClose={() => setPreviewTimeline(false)}
        />
      )}
      <header className="topbar">
        <button
          className="brand"
          onClick={() => {
            activateWorkflowStage("overview");
          }}
          aria-label="返回安影项目概览"
        >
          <AnYingMark />
          <strong>安影</strong>
          <span>STUDIO</span>
        </button>
        <span className="divider" />
        <select className="team-switcher" aria-label="切换团队" value={activeWorkspaceId} onChange={(e)=>void switchWorkspace(e.target.value).catch(report)}>
          {session.workspaces.map((workspace:Any)=><option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}
        </select>
        <button
          className={panel === "projectInfo" ? "project-menu active" : "project-menu"}
          onClick={() => { setProjectSettingsTab("production"); setPanel(panel === "projectInfo" ? null : "projectInfo"); }}
          title="打开当前项目设置"
        >
          <FolderOpen size={15} />
          项目 · {currentProduction?.name || project.name}
          <ChevronDown size={14} />
        </button>
        <WorkflowStageNav
          active={workflowStage}
          onChange={activateWorkflowStage}
          states={Object.fromEntries(Object.entries(workflowGuide.stages).map(([stage, guide]: any) => [stage, guide.state]))}
          episodeControl={<EpisodeSelector episode={project} episodes={currentEpisodes} onSelect={(projectId) => openProject(projectId).catch(report)} />}
        />
        <div className="workflow-header-meta" aria-label={`当前集规格：${doc.ratio} · ${doc.style} · ${doc.duration} 秒`}
          title={`${doc.ratio} · ${doc.style} · ${doc.duration} 秒`}>
          <span>{doc.ratio}</span><i>·</i><span>{doc.style}</span><i>·</i><span>{doc.duration} 秒</span>
        </div>
        <button
          className="project-settings-button"
          aria-label={currentWorkflowScope === "production" ? "打开作品设置" : "打开当前集设置"}
          title={currentWorkflowScope === "production" ? "作品设置" : "当前集设置"}
          onClick={() => { setProjectSettingsTab(currentWorkflowScope); setPanel("projectInfo"); }}
        >
          <FileText size={15} /><span>{currentWorkflowScope === "production" ? "作品设置" : "当前集设置"}</span>
        </button>
        <span
          className={"save-status " + (saved === "保存失败" ? "danger" : "")}
        >
          <span className="status-dot" />
          {saved}
        </span>
        <div className="top-spacer" />
        <button className={panel==='collaboration'?'quiet active':'quiet'}
          onClick={()=>setPanel(panel==='collaboration'?null:'collaboration')}>对象协作</button>
        <button
          className="icon-button"
          aria-label="保存项目"
          title="保存 Ctrl+S"
          onClick={() => void saveCurrentView().catch(report)}
          disabled={(project as Any).permissions?.can_generate===false || !project.object_collaboration}
        >
          <Save size={18} />
        </button>
        <button
          className="avatar"
          onClick={() => { window.location.href='/members'; }}
          title="团队与账号"
        >
          {session.user?.nickname?.slice(0,1)||'我'}
        </button>
      </header>
      <div className="permission-banner">当前角色：{(project as Any).permissions?.role||'只读'}。按对象分工保存；只能编辑自己负责的内容，管理者修改他人对象前须显式接管。{!project.object_collaboration&&' 此旧测试项目为只读，请创建新的协作项目。'}</div>
      <GlobalNav
        active={panel}
        taskCount={activeCount}
        onChange={activateGlobalPanel}
        isAdmin={session.user?.platform_role==='platform_admin'}
      />
      <main className="work-area">
        <div className="viewbar">
          {workflowStage === "storyboard" ? (
            <div className="segmented" aria-label="分镜视图">
              <button className={view === "shots" ? "active" : ""} onClick={() => setView("shots")}>
                <Table2 size={15} />分镜表<span>{doc.shots.length || ""}</span>
              </button>
              <button className={view === "director" ? "active" : ""} onClick={() => setView("director")}>
                3D 导演台
              </button>
              <button onClick={() => activateWorkflowStage("canvas")}>
                高级画布<ArrowUpRight size={13} />
              </button>
            </div>
          ) : workflowStage === "images" ? (
            <div className="segmented" aria-label="分镜图视图">
              <button className={view === "grid" ? "active" : ""} onClick={() => setView("grid")}><LayoutGrid size={15}/>宫格<span>{doc.shots.length || ""}</span></button>
              <button className={view === "shots" ? "active" : ""} onClick={() => setView("shots")}><Table2 size={15}/>列表</button>
              <button onClick={() => activateWorkflowStage("canvas")}>高级画布<ArrowUpRight size={13}/></button>
            </div>
          ) : workflowStage === "editor" ? (
            <strong className="workspace-title"><Scissors size={15} />Twick 多轨剪辑</strong>
          ) : (
            <strong className="workspace-title">
              {{
                overview: "项目概览",
                source: "原著资料",
                adaptation: "改编策划",
                script: "剧本工作区",
                art: "塑角造景",
                images: "分镜图",
                video: "视频工作区",
                canvas: "高级画布",
              }[workflowStage]}
            </strong>
          )}
          {!['overview', 'canvas'].includes(workflowStage) && <WorkflowGuideBanner
            guide={workflowGuide.stages[workflowStage]}
            onNavigate={activateWorkflowStage}
          />}
          {workflowStage === "canvas" && view === "canvas" && (
            <>
            <button className="quiet" onClick={() => setPanel(panel === "add" ? null : "add")}>
              <Plus size={15} />添加节点
            </button>
            <button className="quiet" onClick={() => setPanel("prompts")}>
              <Sparkles size={15} />提示词
            </button>
            <button className="quiet" onClick={() => history().catch(report)}>
              <History size={15} />历史
            </button>
            <button
              className="quiet"
              disabled={!doc.nodes.length}
              onClick={() => {
                update((document) => autoLayoutCanvas(document));
                setSelected(null);
                setLayoutVersion((value) => value + 1);
                setTimeout(() => fitView({ padding: 0.16 }), 100);
                setNotice("画布已按创作链路自动排列");
              }}
              title="按剧本、分镜、视觉资产、分镜图和视频自动排列"
            >
              <LayoutGrid size={15} />
              自动排列
            </button>
            </>
          )}
          {["art", "images", "video", "canvas"].includes(workflowStage) && (
            <div className="batch-generation-actions" aria-label="批量生成">
              {["art", "canvas"].includes(workflowStage) && <button
                className="quiet"
                disabled={busy}
                onClick={() => void runSmartBatch("assets")}
                title={`智能生成缺失的资产参考图；${assetBatchPlan.blocked.length} 项尚未满足条件`}
              >
                <BookOpen size={15} />
                生成全部资产 <b>{assetBatchPlan.readyIds.length}</b>
              </button>}
              {["images", "canvas"].includes(workflowStage) && <button
                className="quiet"
                disabled={busy}
                onClick={() => void runSmartBatch("shot_images")}
                title={`智能生成缺失或过期的分镜图；${imageBatchPlan.blocked.length} 项尚未满足条件`}
              >
                <ImageIcon size={15} />
                全部分镜图 <b>{imageBatchPlan.readyIds.length}</b>
              </button>}
              {["video", "canvas"].includes(workflowStage) && <button
                className="quiet"
                disabled={busy}
                onClick={() => void runSmartBatch("shot_videos")}
                title={`智能生成已有合格首帧的镜头视频；${videoBatchPlan.blocked.length} 项尚未满足条件`}
              >
                <Film size={15} />
                全部视频 <b>{videoBatchPlan.readyIds.length}</b>
              </button>}
            </div>
          )}
          {workflowStage === "canvas" && view !== "editor" && (
              <button
                className="quiet"
                disabled={busy || !doc.nodes.length}
                onClick={() => setPanel("run")}
              >
                <Play size={15} />
                高级运行
              </button>
          )}
        </div>
        {workflowStage === "overview" ? (
          <WorkflowOverview
            projectName={currentProduction?.name || project.name}
            duration={doc.duration}
            ratio={doc.ratio}
            style={doc.style}
            scriptCount={(workflowContext.scripts || []).filter((item: Any) => String(item.script?.body || "").trim()).length}
            visualCount={Object.values(visualBibleOf(doc).cards).filter((card) => !card.deletedAt).length}
            shotCount={doc.shots.length}
            videoCount={doc.nodes.filter((node) => node.data?.kind === "video" && node.data?.assetId).length}
            activeJobs={activeCount}
            guide={workflowGuide}
            onOpenStage={activateWorkflowStage}
          />
        ) : workflowStage === "source" ? (
          <SourceLibraryPage
            store={sourceDrafts.current} actorId={session.user.id}
            canManage={Boolean((project as Any).permissions?.can_manage)} canEdit={(project as Any).permissions?.can_generate!==false}
            productionId={project.production_id}
            projectId={project.id}
            providers={config.models}
            defaultTarget={(doc as Any).generationPolicy?.text}
            refreshKey={workflowDataRevision.source}
            request={api}
            notify={setNotice}
            report={report}
          />
        ) : workflowStage === "adaptation" ? (
          <AdaptationPage
            productionId={project.production_id}
            projectId={project.id}
            providers={config.models}
            defaultTarget={(doc as Any).generationPolicy?.text}
            refreshKey={workflowDataRevision.adaptation}
            request={api}
            notify={setNotice}
            report={report}
            onOpenSource={() => activateWorkflowStage("source")}
            onRevision={(nextRevision) => {
              productionRevision.current = nextRevision;
              setProject((currentProject) => currentProject ? { ...currentProject, production_revision: nextRevision } : currentProject);
              setProductions((items) => items.map((item) => item.id === project.production_id ? { ...item, revision: nextRevision } : item));
            }}
          />
        ) : workflowStage === "script" ? (
          <ScriptRoomPage
            store={scriptDrafts.current} actorId={session.user.id}
            canManage={Boolean((project as Any).permissions?.can_manage)} canEdit={(project as Any).permissions?.can_generate!==false}
            productionId={project.production_id}
            currentEpisodeNo={project.episode_no}
            providers={config.models}
            defaultTarget={(doc as Any).generationPolicy?.text}
            refreshKey={workflowDataRevision.script}
            request={api}
            notify={setNotice}
            report={report}
            onChanged={async (changedProjectId) => {
              await refreshProductionHierarchy();
              if (changedProjectId === project.id&&!ownedUnsaved()) await openProject(project.id);
            }}
            onSelectEpisode={async (episodeNo) => {
              const episode = currentEpisodes.find((item) => item.episode_no === episodeNo);
              if (episode && episode.id !== project.id) await openProject(episode.id);
            }}
            onEnterEpisode={async (episodeNo) => {
              const hierarchy = await refreshProductionHierarchy();
              const episode = episodesForProduction(hierarchy.projects, project.production_id).find((item) => item.episode_no === episodeNo);
              if (episode && episode.id !== project.id) await openProject(episode.id);
              if (!episode) throw new Error(`EP${String(episodeNo).padStart(2, "0")} 尚未建立可制作的 Episode`);
              activateWorkflowStage("storyboard");
            }}
          />
        ) : workflowStage === "art" ? (
          <ArtDepartmentPage
            {...filmBiblePanelProps}
            productionName={currentProduction?.name || project.name}
            usage={visualUsage}
          />
        ) : ["storyboard", "images"].includes(workflowStage) && (view === "shots" || view === "grid") ? (
          <StoryboardWorkspace
            purpose={workflowStage === "images" ? "images" : "planning"}
            mode={view === "grid" ? "grid" : "table"}
            document={doc}
            assets={assets}
            jobs={jobs}
            busy={busy}
            renderImageSettings={(imageNode) => <ImageGenerationSettings node={imageNode} document={doc}
              projectId={project.id} models={config.models} request={api}
              onChange={(patch) => update((d) => patchNode(d,imageNode.id,patch))}/>}
            onPatch={(uid, patch) =>
              update((document) => updateStoryboardShot(document, uid, patch))
            }
            onMove={(uid, offset) =>
              update((document) => moveStoryboardShot(document, uid, offset))
            }
            onCreate={() => {
              update((document) => createStoryboardShot(document, id));
              setNotice("已新建空镜头；填写内容后再显式生成分镜图");
            }}
            onCreatePlan={startStoryboardPlanning}
            onEnsureAll={allShotNodes}
            onAppendTimeline={appendShotTimeline}
            onBind={(uid, versionId) => {
              update((document) => {
                const shot = document.shots.find((item) => shotIdentity(item) === uid);
                const next = bindVisualVersion(document, uid, versionId);
                return invalidate(next, [
                  shot?.imageNode || shot?.pipeline?.imageNodeId,
                  shot?.videoNode || shot?.pipeline?.videoNodeId,
                ].filter(Boolean));
              });
              setNotice("视觉版本已绑定到镜头");
            }}
            onUnbind={(uid, versionId) => {
              update((document) => {
                const shot = document.shots.find((item) => shotIdentity(item) === uid);
                const next = unbindVisualVersion(document, uid, versionId);
                return invalidate(next, [
                  shot?.imageNode || shot?.pipeline?.imageNodeId,
                  shot?.videoNode || shot?.pipeline?.videoNodeId,
                ].filter(Boolean));
              });
              setNotice("视觉版本已从镜头解除");
            }}
            onUpgrade={(uid, cardId, versionId) => {
              update((document) =>
                upgradeVisualBindings(document, cardId, versionId, {
                  shotUids: [uid],
                }),
              );
              setNotice("已显式升级当前镜头的视觉版本；旧画面保留并标记待更新");
            }}
            onGenerate={generateStoryboardImages}
            onOpenCanvas={(shot, index) => {
              if (shot.imageNode || shot.pipeline?.imageNodeId) {
                setSelected(shot.imageNode || shot.pipeline.imageNodeId);
                activateWorkflowStage("canvas");
              } else shotNodes(shot, index);
            }}
            onPreview={setPreview}
            onOpenVideo={() => activateWorkflowStage("video")}
            onExport={async (columns, page) => {
              await save();
              if (dirty.current) throw new Error("请先解决保存冲突");
              const response = await fetch(
                `/api/projects/${project.id}/storyboard-sheet?columns=${columns}&page=${page}`,
              );
              if (!response.ok) throw new Error("分镜图板导出失败");
              const url = URL.createObjectURL(await response.blob());
              const link = document.createElement("a");
              link.href = url;
              link.download = `storyboard-${page}.png`;
              link.click();
              setTimeout(() => URL.revokeObjectURL(url), 5000);
            }}
          />
        ) : workflowStage === "video" ? (
          <VideoProductionWorkspace
            projectId={project.id}
            onUploaded={asset=>setAssets(items=>[asset as Asset,...items])}
            document={doc}
            assets={assets}
            jobs={jobs}
            providers={config.models}
            busy={busy}
            request={api}
            onPatchShot={(uid, patch) =>
              update((document) => updateStoryboardShot(document, uid, patch))
            }
            onPatchVideoNode={(nodeId, patch) =>
              update((document) => patchNode(document, nodeId, patch))
            }
            onGenerate={generateShotVideos}
            onOpenCanvas={(nodeId) => {
              setSelected(nodeId);
              activateWorkflowStage("canvas");
            }}
            onOpenEditor={() => activateWorkflowStage("editor")}
            onPreview={setPreview}
          />
        ) : view === "editor" ? (
          <Suspense fallback={<div className="loading">加载剪辑工作区…</div>}>
            <EditorWorkspace
              projectId={project.id}
              episodes={currentEpisodes}
              productionName={currentProduction?.name || project.name}
              episodeLabel={episodeLabel(project)}
              editor={doc.editor}
              assets={assets}
              ratio={doc.ratio}
              duration={doc.duration}
              shots={doc.shots}
              nodes={doc.nodes}
              audioId={(doc as any).audio_id}
              musicVolume={(doc as any).music_volume ?? 0.3}
              onChange={(editor) =>
                update((currentDoc) => ({ ...currentDoc, editor }))
              }
              onExport={(timeline) => {
                setEditorExportTimeline(timeline);
                setExportSource("editor");
                setPanel("export");
              }}
            />
          </Suspense>
        ) : view === "canvas" ? (
          <div className="canvas">
            <VisualBibleGraphProvider visual={visualBibleOf(doc)} assets={assets}>
            <ReactFlow
              nodes={renderedNodes}
              edges={renderedEdges}
              nodeTypes={nodeTypes}
              onNodesChange={(changes: NodeChange[]) => {
                let measurementsChanged = false;
                for (const change of changes) {
                  if (
                    change.type !== "dimensions" ||
                    !change.dimensions ||
                    (change.dimensions.width == null &&
                      change.dimensions.height == null)
                  )
                    continue;
                  const previous = nodeMeasurements.current.get(change.id);
                  const next = {
                    width: change.dimensions.width ?? previous?.width,
                    height: change.dimensions.height ?? previous?.height,
                  };
                  if (
                    previous?.width !== next.width ||
                    previous?.height !== next.height
                  ) {
                    nodeMeasurements.current.set(change.id, next);
                    measurementsChanged = true;
                  }
                }
                if (measurementsChanged) setLayoutVersion((value) => value + 1);
                const filtered = changes.filter(
                  (c) =>
                    c.type !== "select" &&
                    c.type !== "dimensions" &&
                    !(
                      c.type === "remove" &&
                      doc.nodes.some(
                        (item) =>
                          item.id === c.id && isManagedVisualNode(item as Any),
                      )
                    ),
                );
                if (filtered.length)
                  update((d) => ({
                    ...d,
                    nodes: applyNodeChanges(filtered, d.nodes),
                  }));
              }}
              onEdgesChange={(changes: EdgeChange[]) => {
                if (changes.every((c) => c.type === "select")) return;
                const { allowed, blocked } = filterManagedEdgeRemovals(
                  changes,
                  doc.edges as Any[],
                );
                if (blocked.length)
                  setNotice(
                    "视觉绑定连线由资产关系管理；请在视觉圣经中解除绑定",
                  );
                if (!allowed.length) return;
                update((d) =>
                  invalidate(
                    { ...d, edges: applyEdgeChanges(allowed, d.edges) },
                    d.edges
                      .filter((e) =>
                        allowed.some(
                          (c) => c.type === "remove" && c.id === e.id,
                        ),
                      )
                      .map((e) => e.target),
                  ),
                );
              }}
              onConnect={(connection: Connection) => {
                if (connection.source === connection.target) return;
                const source = doc.nodes.find(
                  (item) => item.id === connection.source,
                );
                const target = doc.nodes.find(
                  (item) => item.id === connection.target,
                );
                if (source && isManagedVisualNode(source as Any)) {
                  const versionId = visualVersionIdFromNode(source as Any);
                  const shot = doc.shots.find(
                    (item) =>
                      item.imageNode === target?.id ||
                      item.pipeline?.imageNodeId === target?.id,
                  );
                  if (!shot || target?.data.kind !== "image") {
                    report(new Error("视觉版本只能连接到分镜图节点"));
                    return;
                  }
                  try {
                    const next = bindVisualVersion(
                      doc,
                      String(shot.uid || shot.id),
                      versionId,
                    );
                    update(() => next);
                    setNotice("已建立视觉绑定，受管连线已同步");
                  } catch (reason) {
                    report(reason);
                  }
                  return;
                }
                if (target && isManagedVisualNode(target as Any)) {
                  report(
                    new Error(
                      "视觉版本节点只接受从自身连向分镜图的绑定操作",
                    ),
                  );
                  return;
                }
                update((d) =>
                  invalidate(
                    {
                      ...d,
                      edges: addEdge({ ...connection, id: id() }, d.edges),
                    },
                    [connection.target],
                  ),
                );
              }}
              onNodeClick={(_, n) => {
                if (isManagedVisualNode(n as Any)) {
                  setSelected(n.id);
                  setVisualFocus(visualVersionIdFromNode(n as Any));
                  setPanel("filmBible");
                  return;
                }
                setSelected(n.id);
                setPanel(null);
              }}
              onNodeMouseEnter={(_, n) => setHoveredNode(n.id)}
              onNodeMouseLeave={() => setHoveredNode(null)}
              onNodeDragStop={(_, n) => {
                requestAnimationFrame(() => updateNodeInternals(n.id));
              }}
              onPaneClick={() => setSelected(null)}
              fitView
              minZoom={0.2}
              maxZoom={1.8}
              defaultEdgeOptions={{
                style: { stroke: "#8f7550", strokeWidth: 1.5 },
                type: "default",
                animated: true,
              }}
              deleteKeyCode={null}
            >
              <Background color="#343739" gap={22} size={1} />
              <Controls showInteractive={false} />
              <MiniMap nodeColor="#5b5545" maskColor="rgba(10,12,13,.6)" />
            </ReactFlow>
            </VisualBibleGraphProvider>
            {!doc.nodes.length && (
              <div className="canvas-welcome">
                <div className="welcome-mark">
                  <Clapperboard size={38} />
                </div>
                <span className="eyebrow">A NEW STORY STARTS HERE</span>
                <h1>故事，从这里开始</h1>
                <p>写下一个念头，将它变成剧本、画面与镜头。</p>
                <div className="welcome-actions">
                  <button
                    className="primary"
                    onClick={() => newNode("text", doc.brief)}
                  >
                    <FileText size={17} />
                    开始写剧本
                  </button>
                  <button onClick={() => fileInput.current?.click()}>
                    <Upload size={17} />
                    导入素材
                  </button>
                </div>
                <div className="starter-strip">
                  <span>也可以直接创建</span>
                  <button onClick={() => newNode("image")}>
                    图像 <Plus size={14} />
                  </button>
                  <button onClick={() => newNode("video")}>
                    视频 <Plus size={14} />
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : view === "director" ? (
          <Suspense fallback={<div className="loading">加载 3D 导演台…</div>}>
            <DirectorStage
              stage={(doc as any).director || defaultStage()}
              onChange={(director) => update((d) => ({ ...d, director }))}
              newId={id}
              onCapture={(blob,prompt)=>captureDirector(blob,prompt,(doc as Any).director||defaultStage())}
            />
          </Suspense>
        ) : null}
        {view !== "editor" && timelineOpen && (
          <section className="timeline">
            <div className="timeline-header">
              <button
                disabled={!doc.timeline.length}
                onClick={() => setPreviewTimeline(true)}
              >
                <Play size={14} />
                连续预览
              </button>
              <span>
                <Scissors size={16} />
                时间线预览{" "}
                <small>
                  {doc.timeline
                    .reduce((sum, t) => sum + Number(t.duration), 0)
                    .toFixed(1)}{" "}
                  秒
                </small>
              </span>
              <label>
                配乐
                <select
                  value={(doc as any).audio_id || ""}
                  onChange={(e) =>
                    update((d) => ({ ...d, audio_id: e.target.value }))
                  }
                >
                  <option value="">无配乐</option>
                  {assets
                    .filter((a) => a.kind === "audio")
                    .map((a) => (
                      <option value={a.id} key={a.id}>
                        {a.name}
                      </option>
                    ))}
                </select>
              </label>
              <button className="quiet" onClick={() => setPanel("assets")}>
                <Plus size={14} />
                添加镜头
              </button>
              <button
                className="primary compact"
                disabled={!doc.timeline.length}
                onClick={() => {
                  setEditorExportTimeline(undefined);
                  setExportSource("legacy");
                  setPanel("export");
                }}
              >
                <Download size={14} />
                导出样片
              </button>
              <button
                className="icon-button"
                onClick={() => setTimelineOpen(false)}
                aria-label="收起时间线"
              >
                <X size={16} />
              </button>
            </div>
            <div className="timeline-clips">
              {!doc.timeline.length ? (
                <p>从素材库将已生成的视频或图片加入时间线</p>
              ) : (
                doc.timeline.map((item, index) => {
                  const a = assets.find((a) => a.id === item.asset_id);
                  return (
                    <div className="timeline-clip" key={item.id}>
                      <Media
                        asset={a}
                        controls={false}
                        retryKey={mediaRetryKey}
                        onFailure={reportMediaFailure}
                        onReady={clearMediaFailure}
                      />
                      <div>
                        <b>
                          {index + 1}. {a?.name || "素材丢失"}
                        </b>
                        <label>
                          起点
                          <input
                            type="number"
                            min="0"
                            value={item.start}
                            onChange={(e) =>
                              update((d) => ({
                                ...d,
                                timeline: d.timeline.map((t) =>
                                  t.id === item.id
                                    ? { ...t, start: Number(e.target.value) }
                                    : t,
                                ),
                              }))
                            }
                          />
                        </label>
                        <label>
                          时长
                          <input
                            type="number"
                            min="0.1"
                            step="0.1"
                            value={item.duration}
                            onChange={(e) =>
                              update((d) => ({
                                ...d,
                                timeline: d.timeline.map((t) =>
                                  t.id === item.id
                                    ? { ...t, duration: Number(e.target.value) }
                                    : t,
                                ),
                              }))
                            }
                          />
                        </label>
                        <label>
                          原声
                          <input
                            aria-label="片段原声音量"
                            type="range"
                            min="0"
                            max="1"
                            step=".05"
                            value={item.volume ?? 1}
                            onChange={(e) =>
                              update((d) => ({
                                ...d,
                                timeline: d.timeline.map((t) =>
                                  t.id === item.id
                                    ? { ...t, volume: Number(e.target.value) }
                                    : t,
                                ),
                              }))
                            }
                          />
                          <small>{Math.round((item.volume ?? 1) * 100)}%</small>
                        </label>
                        <div className="timeline-clip-actions">
                          <button
                            disabled={index === 0}
                            title="前移"
                            onClick={() =>
                              update((d) => {
                                const timeline = [...d.timeline];
                                [timeline[index - 1], timeline[index]] = [
                                  timeline[index],
                                  timeline[index - 1],
                                ];
                                return { ...d, timeline };
                              })
                            }
                          >
                            <ChevronLeft size={13} />
                          </button>
                          <button
                            disabled={index === doc.timeline.length - 1}
                            title="后移"
                            onClick={() =>
                              update((d) => {
                                const timeline = [...d.timeline];
                                [timeline[index], timeline[index + 1]] = [
                                  timeline[index + 1],
                                  timeline[index],
                                ];
                                return { ...d, timeline };
                              })
                            }
                          >
                            <ChevronRight size={13} />
                          </button>
                          <span className="timeline-clip-action-spacer" />
                          <button
                            className="timeline-clip-remove"
                            title="移除镜头"
                            onClick={() =>
                              update((d) => ({
                                ...d,
                                timeline: d.timeline.filter(
                                  (t) => t.id !== item.id,
                                ),
                              }))
                            }
                          >
                            <X size={13} />
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
            <div className="timeline-note">
              保留片段原声。导出面板可添加配乐、字幕和基础转场。
            </div>
          </section>
        )}
      </main>
      {selected && node && !panel && !isManagedVisualNode(node as Any) && (
        <aside className="inspector">
          <div className="inspector-title">
            <span>{titles[data.kind]}设置</span>
            <button
              className="icon-button"
              onClick={() => setSelected(null)}
              aria-label="关闭属性"
            >
              <X size={17} />
            </button>
          </div>
          <div className="inspector-scroll">
            <label>
              节点名称
              <input
                value={data.label || ""}
                onChange={(e) => editNode({ label: e.target.value })}
              />
            </label>
            <div className="field-heading">
              <label>创作描述</label>
              <button className="quiet" onClick={() => setPanel("prompts")}>
                <Sparkles size={13} />
                模板
              </button>
            </div>
            <textarea
              className="prompt-input"
              value={data.prompt || ""}
              onChange={(e) => editNode({ prompt: e.target.value })}
              placeholder={
                data.kind === "text"
                  ? "故事发生在哪里？主角是谁？你想表达什么？"
                  : "描述主体、画面、动作与镜头…"
              }
            />
            {data.kind === "image" && requiresInitialStateReview(data.prompt) && (
              <div className={data.state_reviewed ? "notice" : "danger"}>
                <b>首帧状态核验</b>
                <span>
                  此图要求呈现动作发生前的状态。请确认画面中的灯光、接触关系和开关状态与提示词一致。
                </span>
                {data.assetId ? (
                  data.state_reviewed ? (
                    <small>已确认；关联视频可以使用这张首帧。</small>
                  ) : (
                    <button
                      className="secondary"
                      onClick={() =>
                        update((d) => setInitialStateReviewed(d, node.id))
                      }
                    >
                      已核对首帧状态
                    </button>
                  )
                ) : (
                  <small>生成图片后，在预览画面核对状态，再确认。</small>
                )}
              </div>
            )}
            {data.kind === "video" && pendingInitialStateNodes.length > 0 && (
              <div className="error">
                <div>
                  <b>生成前需要核验首帧</b>
                  <p>
                    关联分镜图「
                    {pendingInitialStateNodes
                      .map((item) => item?.data.label || "未命名分镜图")
                      .join("、")}
                    」尚未确认动作发生前的画面状态。
                  </p>
                  <button
                    className="secondary"
                    onClick={() => {
                      const first = pendingInitialStateNodes[0];
                      if (first) setSelected(first.id);
                    }}
                  >
                    前往核验首帧
                  </button>
                </div>
              </div>
            )}
            {["text", "storyboard"].includes(data.kind) && (
              <details>
                <summary>阶段规则 · 可编辑</summary>
                <textarea
                  className="prompt-input"
                  value={
                    data.system_prompt || system.templates[data.kind] || ""
                  }
                  onChange={(e) => editNode({ system_prompt: e.target.value })}
                />
              </details>
            )}
            {data.kind === "storyboard" && (
              <label>
                分镜目标总时长（秒）
                <input
                  type="number"
                  min="1"
                  max="3000"
                  value={data.target_duration || doc.duration}
                  onChange={(e) =>
                    editNode({ target_duration: Number(e.target.value) })
                  }
                />
                <small>生成后校验总时长，不合格时自动修正一次。</small>
              </label>
            )}
            {data.kind==='video'&&doc.shots.filter(shot=>(shot.videoNode||shot.pipeline?.videoNodeId)===node.id).map(shot=><MotionReferenceEditor
              key={shot.uid||shot.id} document={doc} shot={shot} node={node} assets={assets} models={config.models}
              projectId={project.id} request={api} onUploaded={asset=>setAssets(items=>[asset as Asset,...items])}
              onPatch={patch=>update(document=>updateStoryboardShot(document,shotIdentity(shot),patch))}/>)}
            {data.kind === 'image' ? <ImageGenerationSettings key={node.id} node={node} document={doc}
              projectId={project.id} models={config.models} request={api} onChange={changeModel}/> : <ModelSelector
              data={data}
              providers={config.models}
              localModels={system.models}
              request={api}
              onChange={changeModel}
            />}
            {data.kind === "video" &&
              ["minimax", "volcengine_ark"].includes(
                config.models.find((p: Any) => p.id === data.model_id)
                  ?.type,
              ) &&
              (() => {
                const references = sourceAssets(node.id) as string[];
                const providerType = config.models.find(
                  (p: Any) => p.id === data.model_id,
                )?.type;
                const providerName =
                  providerType === "volcengine_ark" ? "Seedance" : "MiniMax";
                return (
                  <label>
                    首帧（可选，图生视频）
                    <select
                      value={references.length === 1 ? references[0] : ""}
                      onChange={(e) =>
                        setSingleFirstFrame(e.target.value, providerName)
                      }
                    >
                      <option value="">不指定首帧</option>
                      {assets
                        .filter((a) => a.kind === "image")
                        .map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                    </select>
                    <small>
                      选择素材会清除本节点的图像连线和尾帧，只保留这一张首帧；文字连线不受影响。生成时该图会发送到当前配置的视频服务。
                    </small>
                    {references.length > 1 && (
                      <small className="error">
                        当前已有 {references.length} 张图像参考，{providerName}
                        只能使用一张。请选择一张素材以整理引用。
                      </small>
                    )}
                  </label>
                );
              })()}
            {data.kind === "video" &&
              config.models.find((p: Any) => p.id === data.model_id)?.capabilities?.end_frame && (
                <label>
                  尾帧（可选，首尾帧视频）
                  <select
                    value={data.end_asset_id || ""}
                    disabled={sourceAssets(node.id).length !== 1}
                    onChange={(e) =>
                      editNode({ end_asset_id: e.target.value })
                    }
                  >
                    <option value="">不指定尾帧</option>
                    {assets
                      .filter((a) => a.kind === "image")
                      .map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                  </select>
                  <small>
                    先保留一张首帧，再选择同宽高比的尾帧；模型会生成两帧之间的连续运动。
                  </small>
                </label>
              )}
            {["image", "video"].includes(data.kind) &&
              !(
                data.kind === "video" &&
                ["minimax", "volcengine_ark"].includes(
                  config.models.find((p: Any) => p.id === data.model_id)
                    ?.type,
                )
              ) && (
                <>
                  {data.kind === "video" && config.models.find((model:Any)=>model.id===data.model_id)?.capabilities?.end_frame && (
                    <label>
                      尾帧（可选，仅适用模型）
                      <select
                        value={data.end_asset_id || ""}
                        onChange={(e) =>
                          editNode({ end_asset_id: e.target.value })
                        }
                      >
                        <option value="">不使用尾帧</option>
                        {assets
                          .filter((a) => a.kind === "image")
                          .map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}
                            </option>
                          ))}
                      </select>
                      <small>
                        连线或引用图作为首帧，尾帧用于约束镜头结束画面。
                      </small>
                    </label>
                  )}
                  <div className="field-heading">
                    <label>参考素材 · {sourceAssets(node.id).length}</label>
                    <button
                      className="quiet"
                      onClick={() => setPanel("assets")}
                    >
                      <Plus size={14} />
                      引用
                    </button>
                  </div>
                  <div className="reference-strip">
                    {sourceAssets(node.id).map((aid, referenceIndex) => {
                      const a = assets.find((a) => a.id === aid);
                      return a ? (
                        <div className="reference-item" key={String(aid)}>
                          <span className="reference-index">图 {referenceIndex + 1}</span>
                          <button onClick={() => setPreview(a)} title={a.name}>
                            <Media
                              asset={a}
                              controls={false}
                              retryKey={mediaRetryKey}
                              onFailure={reportMediaFailure}
                              onReady={clearMediaFailure}
                            />
                          </button>
                          <button
                            className="reference-remove"
                            title="移除引用及对应连线"
                            aria-label={"移除引用 " + a.name}
                            onClick={() =>
                              update((d) =>
                                removeReference(d, node.id, String(aid)),
                              )
                            }
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ) : null;
                    })}
                  </div>
                </>
              )}
            {activeJob?.status === "failed" && (
              <div className="error">
                <AlertCircle size={16} />
                {activeJob.error}
              </div>
            )}
            {activeJob && ["running", "queued"].includes(activeJob.status) && (
              <div className="job-running">
                <LoaderCircle className="spin" size={16} />
                <span>{activeJob.phase || "等待服务器执行"}</span>
                {activeJob.progress != null && (
                  <b>{Math.round(activeJob.progress)}%</b>
                )}
                <button
                  className="quiet"
                  onClick={() =>
                    api(`/jobs/${activeJob.id}/cancel`, send("POST"))
                      .then(() => refresh(project.id))
                      .catch(report)
                  }
                >
                  取消
                </button>
              </div>
            )}
            {data.text && (
              <details open>
                <summary>{data.kind === "text" ? "剧本正文" : "生成结果"}</summary>
                {data.kind === "text" && !data.canonicalScriptProjection ? (
                  <textarea
                    className="prompt-input canvas-script-editor"
                    value={data.text}
                    onChange={(event) => editNode({ text: event.target.value })}
                    aria-label="画布剧本正文"
                  />
                ) : (
                  <div className="generated-text">{data.text}</div>
                )}
                {data.kind === "text" && !data.canonicalScriptProjection && (
                  <button className="primary full" disabled={busy} onClick={() => void promoteCanvasScript(node).catch(report)}>
                    <FileText size={15} />保存为本集正式剧本
                  </button>
                )}
                {data.kind === "text" && data.canonicalScriptProjection && (
                  <>
                    <button className="secondary full" onClick={() => activateWorkflowStage("script")}>
                      <FileText size={15} />编辑正式剧本
                    </button>
                    {data.scriptStatus === "approved" && (
                      <button className="secondary full" disabled={busy} onClick={() => generateStoryboardFromScript(node)}>
                        <Layers size={15} />生成分镜规划
                      </button>
                    )}
                  </>
                )}
                {data.kind === "storyboard" && activeJob?.result?.shots && (
                  <button
                    className="secondary"
                    onClick={() => adoptShots(activeJob)}
                  >
                    导入分镜表
                  </button>
                )}
              </details>
            )}
            {data.assetId && assets.find((a) => a.id === data.assetId) && (
              <div className="result-preview">
                <Media
                  asset={assets.find((a) => a.id === data.assetId)}
                  retryKey={mediaRetryKey}
                  onFailure={reportMediaFailure}
                  onReady={clearMediaFailure}
                />
                <button
                  onClick={() =>
                    addTimeline(assets.find((a) => a.id === data.assetId)!)
                  }
                >
                  <Scissors size={15} />
                  加入时间线
                </button>
              </div>
            )}
            <details>
              <summary>
                历史生成 · {jobs.filter((j) => j.node_id === selected).length}
              </summary>
              {jobs
                .filter((j) => j.node_id === selected)
                .map((j) => (
                  <div className="take" key={j.id}>
                    <span>
                      {new Date(j.created * 1000).toLocaleTimeString()} ·{" "}
                      {states[j.status]}
                    </span>
                    {j.result?.assets?.[0] && (
                      <button
                        onClick={() => setPanel("jobs")}
                      >
                        比较并采纳此版本
                      </button>
                    )}
                    {j.result?.text && (
                      <button
                        onClick={() => setPanel("jobs")}
                      >
                        比较并采纳此文本
                      </button>
                    )}
                  </div>
                ))}
            </details>
          </div>
          <div className="inspector-bottom">
            <button
              className="icon-button"
              onClick={() => {
                newNode(data.kind, data.prompt, {
                  ...data,
                  assetId: undefined,
                  text: undefined,
                  resultJob: undefined,
                });
              }}
              title="复制节点"
            >
              <Copy size={17} />
            </button>
            <button
              className="icon-button"
              onClick={removeNode}
              title="移除节点"
            >
              <Trash2 size={17} />
            </button>
            <button
              className="primary"
              disabled={
                busy ||
                ["running", "queued"].includes(activeJob?.status || "") ||
                !data.prompt?.trim()
              }
              onClick={() => run()}
            >
              <Play size={16} />
              {data.resultJob ? "重新生成" : "开始生成"}
            </button>
          </div>
        </aside>
      )}
      {panel && <div className="side-panel-scrim" onClick={() => setPanel(null)} aria-hidden="true" />}
      {panel && (
        <div
          className={
            "side-panel " +
            (["settings", "assets", "jobs", "characters", "filmBible", "projectInfo", "trash", "collaboration"].includes(
              panel,
            )
              ? panel === "filmBible"
                ? "film-bible-wide"
                : "wide"
              : "")
          }
        >
          <div className="panel-title">
            <h2>
              {
                {
                  add: "添加节点",
                  projects: "项目库",
                  projectInfo: "项目设置",
                  assets: "资产中心",
                  jobs: "生成任务",
                  settings: "设置",
                  prompts: "提示词模板",
                  history: "历史版本",
                  characters: "角色与场景",
                  export: "导出成片",
                  run: "运行工作流",
                  filmBible: "视觉圣经",
                  trash: "回收站",
                  collaboration: "对象分工与协作",
                }[panel]
              }
            </h2>
            <button
              className="icon-button"
              onClick={() => setPanel(null)}
              aria-label="关闭面板"
            >
              <X size={19} />
            </button>
          </div>
          <div className="panel-scroll">
            {panel === "collaboration" && <CollaborationPanel key={project.id}
              client={collaboration.current!} document={doc} assets={assets} actorId={session.user.id}
              canManage={Boolean((project as Any).permissions?.can_manage)}
              canEdit={(project as Any).permissions?.can_generate!==false}
              request={api} onDocument={acceptObjectDocument} onSave={saveObject} />}
            {panel === "filmBible" && <FilmBiblePanel {...filmBiblePanelProps} />}
            {panel === "run" && (
              <RunWorkflow
                nodes={doc.nodes}
                edges={doc.edges}
                providers={config.models}
                selected={selected}
                onRun={runGraph}
              />
            )}
            {panel === "add" && (
              <div className="node-menu">
                {["text", "storyboard", "image", "video"].map((kind) => {
                  const Icon = icons[kind];
                  return (
                    <button key={kind} onClick={() => newNode(kind)}>
                      <Icon />
                      <div>
                        <b>{titles[kind]}</b>
                        <span>
                          {
                            {
                              text: "从故事概念开始",
                              storyboard: "将剧本拆解为镜头",
                              image: "生成画面与角色定妆",
                              video: "生成动态镜头",
                            }[kind]
                          }
                        </span>
                      </div>
                      <Plus size={17} />
                    </button>
                  );
                })}
                <button onClick={() => fileInput.current?.click()}>
                  <Upload />
                  <div>
                    <b>导入素材</b>
                    <span>图片、视频、声音与字幕</span>
                  </div>
                </button>
              </div>
            )}
            {panel === "projects" && (
              <ProductionLibrary
                productions={productions}
                episodes={projects}
                currentEpisodeId={project.id}
                onCreateProduction={openProjectSetup}
                onOpenProjectSettings={() => { setProjectSettingsTab("production"); setPanel("projectInfo"); }}
                onCreateEpisode={(production) => {
                  const next = episodesForProduction(projects, production.id).length + 1;
                  const title = window.prompt(`在“${production.name}”中新增 EP${String(next).padStart(2, "0")}，可填写集名：`, `第 ${String(next).padStart(2, "0")} 集`);
                  if (title !== null) createEpisode(production, title).catch(report);
                }}
                onOpenEpisode={(episode) => openProject(episode.id).catch(report)}
                onDeleteEpisode={(episode) => deleteProject(episode.id === project.id ? { ...episode, name: project.name } : episode).catch(report)}
              />
            )}
            {panel === "trash" && (
              <>
                <p className="muted">这里只隐藏内容，不删除数据库记录和媒体文件。恢复后会回到原来的项目。</p>
                {!!trashItems.projects.length && <h3>项目</h3>}
                {trashItems.projects.map((item: Any) => (
                  <div className="trash-row" key={`project-${item.id}`}>
                    <FolderOpen size={17} />
                    <div><b>{item.name}</b><small>{new Date(item.deleted_at * 1000).toLocaleString()}</small></div>
                    <button onClick={() => restoreTrashItem("project", item).catch(report)}><RefreshCw size={14} /> 恢复</button>
                  </div>
                ))}
                {!!trashItems.assets.length && <h3>素材</h3>}
                {trashItems.assets.map((item: Any) => (
                  <div className="trash-row" key={`asset-${item.id}`}>
                    <ImageIcon size={17} />
                    <div><b>{item.name}</b><small>{item.project_name} · {assetKinds[item.kind] || item.kind}</small></div>
                    <button onClick={() => restoreTrashItem("asset", item).catch(report)}><RefreshCw size={14} /> 恢复</button>
                  </div>
                ))}
                {!!trashItems.sources?.length && <h3>原著资料</h3>}
                {trashItems.sources?.map((item: Any) => (
                  <div className="trash-row" key={`source-${item.id}`}>
                    <BookOpen size={17} />
                    <div><b>{item.name}</b><small>{item.production_name} · {item.chapter_count} 章</small></div>
                    <button onClick={() => restoreTrashItem("source", item).catch(report)}><RefreshCw size={14} /> 恢复</button>
                  </div>
                ))}
                {!!trashItems.chapters?.length && <h3>原著章节</h3>}
                {trashItems.chapters?.map((item: Any) => (
                  <div className="trash-row" key={`chapter-${item.id}`}>
                    <BookOpen size={17} />
                    <div><b>{item.name}</b><small>{item.production_name} · {item.source_name}</small></div>
                    <button onClick={() => restoreTrashItem("chapter", item).catch(report)}><RefreshCw size={14} /> 恢复</button>
                  </div>
                ))}
                {!!doc.characters.filter((item) => item.deletedAt).length && <h3>当前项目角色 / 场景</h3>}
                {doc.characters.filter((item) => item.deletedAt).map((item) => (
                  <div className="trash-row" key={`character-${item.id}`}>
                    <FolderOpen size={17} />
                    <div><b>{item.name}</b><small>手工角色 / 场景设定</small></div>
                    <button onClick={() => {
                      update((d) => ({
                        ...d,
                        characters: d.characters.map((candidate) => {
                          if (candidate.id !== item.id) return candidate;
                          const restored = { ...candidate };
                          delete restored.deletedAt;
                          return restored;
                        }),
                      }));
                      setNotice(`角色/场景“${item.name}”已恢复`);
                    }}><RefreshCw size={14} /> 恢复</button>
                  </div>
                ))}
                {!!Object.values(visualBibleOf(doc).cards).filter((item) => item.deletedAt).length && <h3>当前项目视觉资产卡</h3>}
                {Object.values(visualBibleOf(doc).cards).filter((item) => item.deletedAt).map((item) => (
                  <div className="trash-row" key={`visual-${item.id}`}>
                    <BookOpen size={17} />
                    <div><b>{item.name}</b><small>{assetCategories[item.kind === "character_state" ? "character" : item.kind === "scene_state" ? "scene" : item.kind] || item.kind}</small></div>
                    <button onClick={() => {
                      update((currentDoc) => restoreVisualCard(currentDoc, item.id));
                      setNotice(`视觉资产卡“${item.name}”已恢复`);
                    }}><RefreshCw size={14} /> 恢复</button>
                  </div>
                ))}
                {!trashItems.projects.length && !trashItems.assets.length && !trashItems.sources?.length && !trashItems.chapters?.length && !doc.characters.some((item) => item.deletedAt) && !Object.values(visualBibleOf(doc).cards).some((item) => item.deletedAt) && (
                  <div className="empty-state"><Trash2 /><h3>回收站为空</h3><p>移入回收站的项目、素材、原著和角色场景会显示在这里。</p></div>
                )}
              </>
            )}
            {panel === "projectInfo" && (
              <>
                <div className="current-project-card">
                  <AnYingMark size={30} />
                  <div>
                    <small>{projectSettingsTab === "production" ? "整部作品" : "当前制作集"}</small>
                    <b>{currentProduction?.name || project.name} · {episodeLabel(project)}</b>
                  </div>
                </div>
                <div className="settings-tabs" role="tablist" aria-label="项目设置范围">
                  <button className={projectSettingsTab === "production" ? "active" : ""} onClick={() => setProjectSettingsTab("production")}>整部作品</button>
                  <button className={projectSettingsTab === "episode" ? "active" : ""} onClick={() => setProjectSettingsTab("episode")}>当前制作集</button>
                </div>
                {sessionStorage.getItem("yingxu-conflict-" + project.id) && (
                  <div className="error">
                    <p>
                      本页保留了一份冲突草稿。恢复后将作为新的编辑保存；主机当前版本仍可在历史版本中找到。
                    </p>
                    <button
                      onClick={() => {
                        try {
                          const draft = JSON.parse(
                            sessionStorage.getItem(
                              "yingxu-conflict-" + project.id,
                            )!,
                          );
                          update(() => draft.document);
                          setProject({ ...project, name: draft.name });
                          setNotice("冲突草稿已恢复为当前编辑");
                        } catch (e) {
                          report(e);
                        }
                      }}
                    >
                      恢复本页冲突草稿
                    </button>
                  </div>
                )}
                {projectSettingsTab === "production" ? <>
                  <h3>整部作品设置</h3>
                  <label>作品名称<div className="inline-save-field"><input maxLength={100} value={productionNameDraft} onChange={(event)=>setProductionNameDraft(event.target.value)}/><button disabled={!productionNameDraft.trim() || productionNameDraft.trim() === currentProduction?.name} onClick={()=>renameProduction(productionNameDraft).catch(report)}>保存名称</button></div><small>修改作品名称不会改变任何 Episode 标题，也不会触发生成。</small></label>
                  <div className="visual-style-setting">
                    <VisualStylePicker value={visualStyleDraft} onChange={setVisualStyleDraft} label="高层视觉风格" hint="选择预设或直接输入自定义风格。应用后会统一进入资产、分镜图和视频的生成上下文。"/>
                    <button disabled={!visualStyleDraft.trim() || visualStyleDraft.trim() === doc.style} onClick={()=>{update((document)=>setProjectVisualStyle(document,visualStyleDraft.trim()));setNotice("视觉风格已应用；旧媒体保留，相关生成结果已标记为待更新");}}>应用风格</button>
                    <small>修改后会把已生成的分镜图和视频标记为待更新；旧媒体和剪辑内容会保留，不会自动生成。</small>
                  </div>
                  <GenerationPolicyPanel value={doc.generationPolicy} providers={config.models} localModels={system.models} onChange={(generationPolicy)=>update((document)=>({...document,generationPolicy}))}/>
                  <div className="project-bible-heading"><div><span className="eyebrow">PROJECT BIBLE</span><h3>创作约束</h3></div><button className="quiet" onClick={()=>setPanel("filmBible")}><BookOpen size={15}/>打开塑角造景 {Object.keys(visualBibleOf(doc).cards).length || ""}<ChevronRight size={14}/></button></div>
                  <p className="muted">这里只修改文字约束，不会覆盖已有 VisualCard、VisualVersion 或锁定参考图。</p>
                  <label>世界 / 时代<input value={projectBibleFields.worldEra} onChange={(event)=>update((document)=>mergeBibleFields(document,{...bibleFields(document),worldEra:event.target.value}))}/></label>
                  <div className="two-fields">
                    <label>视觉基调<input value={projectBibleFields.visualTone} onChange={(event)=>update((document)=>mergeBibleFields(document,{...bibleFields(document),visualTone:event.target.value}))}/></label>
                    <label>色彩 / 光线<input value={projectBibleFields.colorLighting} onChange={(event)=>update((document)=>mergeBibleFields(document,{...bibleFields(document),colorLighting:event.target.value}))}/></label>
                  </div>
                  <label>镜头语言<input value={projectBibleFields.cameraLanguage} onChange={(event)=>update((document)=>mergeBibleFields(document,{...bibleFields(document),cameraLanguage:event.target.value}))}/></label>
                  <label>角色 / 场景一致性<textarea value={projectBibleFields.characterSceneConsistency} onChange={(event)=>update((document)=>mergeBibleFields(document,{...bibleFields(document),characterSceneConsistency:event.target.value}))}/></label>
                  <label>避免项（每行一项）<textarea value={projectBibleFields.avoidItems} onChange={(event)=>update((document)=>mergeBibleFields(document,{...bibleFields(document),avoidItems:event.target.value}))}/></label>
                </> : <>
                  <h3>当前制作集设置</h3>
                  <label>默认对白方式<select value={(doc as Any).dialogueMode||'full_dialogue'} onChange={event=>update(document=>({...document,dialogueMode:event.target.value}))}><option value="voice_sample">音色样本参考</option><option value="full_dialogue">完整对白参考</option></select><small>音色样本须配合多模态模型，台词使用本镜对白。</small></label>
                  <label>视频参考模式<select value={(doc as any).videoReferenceMode||'legacy'} onChange={event=>update(document=>({...document,videoReferenceMode:event.target.value}))}>{Object.entries(videoModeLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select><small>仅影响本集跟随默认模式的镜头，原素材保留。</small></label>
                  <label>Episode 标题<input maxLength={100} value={project.name} onChange={(event)=>{setProject({...project,name:event.target.value,episode_title:event.target.value});dirty.current=true;setSaved("未保存");}}/><small>只修改当前 EP{String(project.episode_no).padStart(2,"0")}，不会改变整部作品名称。</small></label>
                  <label>创作简介<textarea value={doc.brief} onChange={(event)=>update((document)=>({...document,brief:event.target.value}))}/></label>
                  <div className="two-fields">
                    <label>图像画幅<select value={doc.ratio} onChange={(event)=>{update((document)=>applyRatioChange(document,event.target.value));setNotice("画幅已修改；已有分镜图和视频保留并标记为待更新");}}><option>21:9</option><option>16:9</option><option>4:3</option><option>1:1</option><option>3:4</option><option>9:16</option></select><small>资产图与分镜图按该比例生成。</small></label>
                    <label>目标时长（秒）<input type="number" min="5" max="3000" value={doc.duration} onChange={(event)=>update((document)=>applyTargetDuration(document,Number(event.target.value)))}/><small>策划目标，不会裁剪已有镜头或成片。</small></label>
                    <label>视频分辨率<select value={doc.videoResolution || "720p"} onChange={(event)=>{update((document)=>applyVideoResolution(document,event.target.value));setNotice("视频分辨率已修改；已有视频保留并标记为待更新");}}>{VIDEO_RESOLUTIONS.map((value)=><option key={value} value={value}>{value === "1080p" ? "1080p（10bit 位深）" : `${value}（8bit 位深）`}</option>)}</select><small>所有新视频任务继承该设置。</small></label>
                    <label>视频宽高比<select value={doc.videoRatio || doc.ratio || "16:9"} onChange={(event)=>update((document)=>applyVideoOutputSetting(document,{videoRatio:event.target.value}))}>{VIDEO_RATIOS.map((value)=><option key={value}>{value}</option>)}</select><small>首帧模型可选择 adaptive。</small></label>
                    <label>视频输出时长<select value={doc.videoDuration ?? -1} onChange={(event)=>update((document)=>applyVideoOutputSetting(document,{videoDuration:Number(event.target.value)}))}><option value={-1}>-1（按分镜和对白自动）</option>{Array.from({length:27},(_,index)=>index+4).map((value)=><option key={value} value={value}>{value} 秒</option>)}</select><small>默认使用分镜时长；对白更长时自动延长。</small></label>
                    <label>视频格式<select value={doc.videoFormat || "mp4"} onChange={(event)=>update((document)=>applyVideoOutputSetting(document,{videoFormat:event.target.value}))}>{VIDEO_FORMATS.map((value)=><option key={value}>{value}</option>)}</select><small>用于输出与导出。</small></label>
                  </div>
                  <div className="duration-impact"><span>目标 {doc.duration} 秒</span><span>镜头合计 {doc.shots.reduce((sum,shot)=>sum+Number(shot.duration||0),0).toFixed(1)} 秒</span><span>剪辑 {Math.max(0,...(doc.editor?.timeline?.tracks||[]).flatMap((track)=>track.elements.map((element)=>Number(element.e)||0))).toFixed(1)} 秒</span></div>
                </>}
                <button
                  className="full danger-button"
                  onClick={() => deleteProject(project).catch(report)}
                >
                  <Trash2 size={16} />
                  将项目移入回收站
                </button>
              </>
            )}
            {panel === "assets" && (
              <ProductionAssetCenter
                document={doc}
                assets={assets}
                projects={currentEpisodes}
                currentProjectId={project.id}
                usage={visualUsage}
                uploadCategory={uploadCategory}
                onUploadCategory={setUploadCategory}
                onUpload={() => fileInput.current?.click()}
                onCreatePanorama={() => {
                  const defaults=nodeDefaults('image',config.models,system.models,doc.generationPolicy);
                  const model=config.models.find((item:Any)=>item.id===defaults.model_id)||{};
                  newNode(
                  "image",
                  "生成 360 度等距柱状全景环境图，2:1 画幅，完整覆盖四周环境，上下分别为天空与地面，左右边缘连续，地平线位于画面中线，无文字。场景：",
                  {image_purpose:'panorama',parameters:shotParameters('image',model,defaults.parameters,{},'2:1')},
                );}}
                onOpenArt={(versionId) => {
                  setVisualFocus(versionId);
                  activateWorkflowStage("art");
                }}
                onPreview={(asset) => setPreview(asset as Asset)}
                renderMedia={(asset) => <Media asset={asset as Asset} controls={false} retryKey={mediaRetryKey} onFailure={reportMediaFailure} onReady={clearMediaFailure} />}
                onCategory={(asset, category) => void changeAssetCategory(asset as Asset, category)}
                onDelete={(asset) => void deleteAsset(asset as Asset)}
                onTimeline={(asset) => addTimeline(asset as Asset)}
                onPanorama={(asset) => setPanorama(asset as Asset)}
                onReference={selected ? (asset) => {
                  editNode({ asset_ids: [...new Set([...(data.asset_ids || []), asset.id])] });
                  setPanel(null);
                } : undefined}
              />
            )}
            {panel === "jobs" && (
              <TaskCenter
                key={project.production_id}
                productionName={currentProduction?.name || project.name}
                episodes={currentEpisodes}
                currentProjectId={project.id}
                currentDocument={doc}
                currentJobs={jobs}
                providers={config.models}
                request={api}
                onRefreshCurrent={() => refresh(project.id)}
                onOpenNode={async (projectId, nodeId) => {
                  if (projectId !== project.id) await openProject(projectId);
                  setSelected(nodeId);
                  activateWorkflowStage("canvas");
                }}
                onAdoptShots={(job) => adoptShots(job as Job)}
                onAdoptCandidate={async(job,body)=>{
                  const snapshot=current.current;
                  if(!snapshot.project||snapshot.project.production_id!==job.production_id)
                    throw new Error('作品已切换，不能从旧任务列表采纳');
                  requireOwnedSaved();
                  if(dirty.current||saveFlight.current)throw new Error('请先保存或处理当前对象草稿，再采纳候选');
                  const generation=collaboration.current!.drafts.generation;
                  await api(`/projects/${job.project_id}/candidates/${job.id}/adopt`,send('POST',body));
                  if(current.current.project?.id!==snapshot.project.id||collaboration.current!.drafts.generation!==generation)return;
                  setWorkflowDataRevision(value=>({source:value.source+1,adaptation:value.adaptation+1,script:value.script+1}));
                  await refresh(snapshot.project.id);
                  if(current.current.project?.id!==snapshot.project.id||collaboration.current!.drafts.generation!==generation)return;
                  if(!dirty.current&&!saveFlight.current&&!ownedUnsaved())await openProject(snapshot.project.id);
                  setNotice('候选已明确采纳；若操作期间产生了新草稿，会保留草稿供比较。');
                }}
              />
            )}
            {panel === "export" && (
              <>
                <div className="export-summary">
                  <Film size={30} />
                  <h3>{project.name}</h3>
                  <strong>{exportSource === "editor" ? "高级剪辑" : "时间线预览"}</strong>
                  <p>
                    {exportSource === "editor"
                      ? `${exportEditorTracks.length} 条编辑轨 · ${Math.max(0, ...exportEditorTracks.flatMap((track) => track.elements.map((element) => Number(element.e) || 0))).toFixed(2)} 秒`
                      : `${doc.timeline.length} 个镜头 · ${doc.timeline.reduce((sum, t) => sum + Number(t.duration), 0).toFixed(2)} 秒`}
                  </p>
                </div>
                <label>
                  导出分辨率
                  <select
                    value={(doc as any).export_resolution || "1280x720"}
                    onChange={(e) =>
                      update((d) => ({
                        ...d,
                        export_resolution: e.target.value,
                      }))
                    }
                  >
                    <option value="1280x720">720P · 横屏</option>
                    <option value="1920x1080">1080P · 横屏</option>
                    <option value="720x1280">720P · 竖屏</option>
                    <option value="1080x1920">1080P · 竖屏</option>
                    <option value="1080x1080">1080 · 方形</option>
                  </select>
                </label>
                <label>
                  转场
                  <select
                    disabled={exportSource === "editor"}
                    value={(doc as any).transition || "cut"}
                    onChange={(e) =>
                      update((d) => ({ ...d, transition: e.target.value }))
                    }
                  >
                    <option value="cut">直接切换</option>
                    <option value="fade">淡入淡出</option>
                  </select>
                </label>
                <label>
                  背景配乐
                  <select
                    disabled={exportSource === "editor"}
                    value={(doc as any).audio_id || ""}
                    onChange={(e) =>
                      update((d) => ({ ...d, audio_id: e.target.value }))
                    }
                  >
                    <option value="">不添加</option>
                    {assets
                      .filter((a) => a.kind === "audio")
                      .map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  配乐音量 ·{" "}
                  {Math.round(((doc as any).music_volume ?? 0.3) * 100)}%
                  <input
                    disabled={exportSource === "editor"}
                    type="range"
                    min="0"
                    max="1"
                    step=".05"
                    value={(doc as any).music_volume ?? 0.3}
                    onChange={(e) =>
                      update((d) => ({
                        ...d,
                        music_volume: Number(e.target.value),
                      }))
                    }
                  />
                </label>
                <label>
                  烧录字幕（SRT）
                  <select
                    disabled={exportSource === "editor"}
                    value={(doc as any).subtitle_id || ""}
                    onChange={(e) =>
                      update((d) => ({ ...d, subtitle_id: e.target.value }))
                    }
                  >
                    <option value="">不添加</option>
                    {assets
                      .filter((a) => a.kind === "subtitle")
                      .map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                  </select>
                </label>
                <button
                  className="quiet"
                  onClick={() => fileInput.current?.click()}
                >
                  <Upload size={15} />
                  上传配乐或字幕
                </button>
                <p className="muted">
                  {exportSource === "editor"
                    ? "当前导出 Twick 多轨工程。配乐、字幕、转场和音量请在剪辑工作区中调整。输出为 24fps H.264/AAC MP4。"
                    : "MP4 / H.264 / 24fps。保留镜头原声，配乐循环填充时间线。字幕烧录进视频画面。"}
                </p>
                <button
                  className="primary full"
                  disabled={exportSource === "editor"
                    ? !exportEditorTracks.some((track) => track.elements.length)
                    : !doc.timeline.length}
                  onClick={() => void exportFilm(exportSource, editorExportTimeline)}
                >
                  <Download size={17} />
                  开始导出
                </button>
              </>
            )}
            {panel === "settings" && (
              <SettingsPanel
                config={config}
                system={system}
                onSave={async (value) => {
                  setConfig(await api("/settings", send("PUT", value)));
                  setSystem(await api("/system"));
                  setNotice("设置已保存");
                }}
                onRefresh={async () => setSystem(await api("/system"))}
                onError={report}
                onLogout={async () => {
                  await save();
                  await api("/auth/logout", send("POST"));
                  onLogout();
                }}
              />
            )}
            {panel === "prompts" && (
              <PromptLibrary
                canManage={session.user?.platform_role === 'platform_admin'}
                templates={system.templates}
                request={api}
                newId={id}
                onApply={(kind, content) => {
                  const patch = ["text", "storyboard"].includes(kind)
                    ? { system_prompt: content }
                    : { prompt: content };
                  if (selected && data.kind === kind) editNode(patch);
                  else newNode(kind, "", patch);
                  setPanel(null);
                  setNotice("模板已应用，可继续编辑");
                }}
              />
            )}
            {panel === "history" && (
              <>
                {revisions.map((r) => (
                  <div className="history-row" key={r.id}>
                    <div>
                      <b>版本 {r.revision}</b>
                      <small>
                        {new Date(r.created * 1000).toLocaleString()}
                      </small>
                    </div>
                    <button
                      onClick={async () => {
                        try {
                          const old = await api(
                            `/projects/${project.id}/revisions/${r.id}`,
                          );
                          update(() => old.document);
                          setPanel(null);
                          setNotice("历史版本已载入，当前内容会另存为新版本");
                        } catch (e) {
                          report(e);
                        }
                      }}
                    >
                      恢复
                    </button>
                  </div>
                ))}
                {!revisions.length && (
                  <p className="muted">保存项目后会自动保留历史版本。</p>
                )}
              </>
            )}
            {panel === "characters" && (
              <>
                <p className="muted">
                  建立可复用的角色与场景设定，绑定参考图锁定外观。
                </p>
                <button
                  className="secondary full"
                  onClick={() =>
                    update((d) => ({
                      ...d,
                      characters: [
                        ...d.characters,
                        {
                          id: id(),
                          name: "新角色",
                          description: "",
                          asset_id: "",
                        },
                      ],
                    }))
                  }
                >
                  <Plus size={16} />
                  添加角色 / 场景
                </button>
                {doc.characters.filter((c) => !c.deletedAt).map((c) => (
                  <article className="character-card" key={c.id}>
                    <label>
                      名称
                      <input
                        value={c.name}
                        onChange={(e) =>
                          update((d) => ({
                            ...d,
                            characters: d.characters.map((x) =>
                              x.id === c.id
                                ? { ...x, name: e.target.value }
                                : x,
                            ),
                          }))
                        }
                      />
                    </label>
                    <label>
                      固定设定
                      <textarea
                        value={c.description}
                        placeholder="外观、服装、材质或场景特征"
                        onChange={(e) =>
                          update((d) => ({
                            ...d,
                            characters: d.characters.map((x) =>
                              x.id === c.id
                                ? { ...x, description: e.target.value }
                                : x,
                            ),
                          }))
                        }
                      />
                    </label>
                    <label>
                      参考图
                      <select
                        value={c.asset_id}
                        onChange={(e) =>
                          update((d) => ({
                            ...d,
                            characters: d.characters.map((x) =>
                              x.id === c.id
                                ? { ...x, asset_id: e.target.value }
                                : x,
                            ),
                          }))
                        }
                      >
                        <option value="">选择素材</option>
                        {assets
                          .filter((a) => a.kind === "image")
                          .map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    {selected && (
                      <button
                        onClick={() => {
                          editNode({
                            prompt:
                              (data.prompt || "") +
                              "\n角色/场景 " +
                              c.name +
                              "：" +
                              c.description,
                            asset_ids: c.asset_id
                              ? [
                                  ...new Set([
                                    ...(data.asset_ids || []),
                                    c.asset_id,
                                  ]),
                                ]
                              : data.asset_ids || [],
                          });
                          setPanel(null);
                        }}
                      >
                        <Link2 size={14} />
                        引用到当前节点
                      </button>
                    )}
                    <button
                      className="quiet danger"
                      onClick={() => {
                        if (!window.confirm(`将角色/场景“${c.name}”移入回收站？`)) return;
                        update((d) => ({
                          ...d,
                          characters: d.characters.map((item) =>
                            item.id === c.id
                              ? { ...item, deletedAt: Date.now() / 1000 }
                              : item,
                          ),
                        }));
                        setNotice(`角色/场景“${c.name}”已移入回收站`);
                      }}
                    >
                      <Trash2 size={14} /> 移至回收站
                    </button>
                  </article>
                ))}
              </>
            )}
          </div>
        </div>
      )}
      <input
        type="file"
        ref={fileInput}
        multiple
        accept="image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime,audio/*,.srt"
        hidden
        onChange={(e) => {
          uploadFiles(e.target.files, uploadCategory);
          e.target.value = "";
        }}
      />
      {conflict && panel!=='collaboration' && (
        <div className="modal-overlay">
          <div
            className="panorama-modal"
            role="dialog"
            aria-modal="true"
            aria-label="解决保存冲突"
          >
            <h2>对象版本发生冲突</h2>
            <p>
              本页草稿仍然保留，自动保存已暂停。可在对象协作中逐个比较和处理冲突，
              也可以备份整页草稿后重新载入。
            </p>
            <button onClick={()=>setPanel('collaboration')}>比较并处理单个对象</button>
            <button
              className="primary"
              disabled={recoveryBusy}
              onClick={recoverConflict}
            >
              {recoveryBusy ? "正在载入" : "备份本页草稿并载入最新版本"}
            </button>
          </div>
        </div>
      )}
      {notice && (
        <div className="toast">
          <Check size={16} />
          {notice}
        </div>
      )}
      {syncFailure && (
        <div className={`sync-toast ${syncFailure.kind}`} role="status">
          {syncFailure.kind === "api" ? (
            <RefreshCw size={18} className="spin" />
          ) : (
            <AlertCircle size={18} />
          )}
          <div>
            <strong>
              {syncFailure.kind === "api"
                ? "API 请求失败"
                : syncFailure.kind === "sse"
                  ? "SSE 实时连接断开"
                  : "媒体文件加载失败"}
            </strong>
            <span>{syncFailure.message}</span>
            <small>
              开发调试 · 请求 URL：<code>{syncFailure.url}</code>
            </small>
          </div>
        </div>
      )}
      {error && (
        <div className="error-toast" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
          <button onClick={() => setError("")} aria-label="关闭错误">
            <X size={16} />
          </button>
        </div>
      )}
      {panorama && (
        <PanoramaViewer
          asset={panorama}
          onClose={() => setPanorama(null)}
          onSave={async (blob, name) => {
            const form = new FormData();
            form.append("file", blob, name);
            await api(`/projects/${project.id}/assets`, {
              method: "POST",
              body: form,
            });
            await refresh(project.id);
            setNotice("全景构图已保存，可引用到生成节点");
          }}
        />
      )}
      {preview && (
        <div className="modal-overlay" onClick={() => setPreview(null)}>
          <div className="media-modal" onClick={(e) => e.stopPropagation()}>
            <div>
              <h3>{preview.name}</h3>
              <button
                className="icon-button"
                onClick={() => setPreview(null)}
                aria-label="关闭预览"
              >
                <X />
              </button>
            </div>
            <Media
              asset={preview}
              retryKey={mediaRetryKey}
              onFailure={reportMediaFailure}
              onReady={clearMediaFailure}
            />
            <a
              className="download-link"
              href={preview.url}
              download={preview.name}
            >
              <Download size={16} />
              下载原文件
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

function SettingsPanel({config,onSave,onRefresh,onError,onLogout}:{
 config:Any;system:Any;onSave:(value:Any)=>Promise<void>;onRefresh:()=>Promise<void>;onError:(e:any)=>void;onLogout:()=>void;
}){
 const [ffmpeg,setFfmpeg]=useState(config.ffmpeg||'ffmpeg'),[busy,setBusy]=useState(false),[status,setStatus]=useState('');
 async function saveFfmpeg(){
  setBusy(true);try{await onSave({ffmpeg});setStatus('FFmpeg 设置已保存')}catch(error){onError(error)}finally{setBusy(false)}
 }
 return <><h3>平台模型目录</h3><p className="muted">外部 API-only：Provider、Key 和上游模型由平台管理员统一管理。创作页面只选择已发布的平台模型。</p>
 {!config.read_only&&<a href="/admin">进入平台模型管理</a>}
 {!config.models?.length&&<p className="error">暂无可用平台模型，请联系管理员；不会自动回退其他服务。</p>}
 {(config.models||[]).map((model:Any)=><p key={model.id}>{model.name} · {model.kind}</p>)}
 <button className="quiet" onClick={()=>void onRefresh().catch(onError)}><RefreshCw size={14}/>刷新目录</button>
 {!config.read_only&&<><hr/><label>FFmpeg 路径<input value={ffmpeg} onChange={e=>setFfmpeg(e.target.value)}/></label>
 <button className="primary" disabled={busy} onClick={()=>void saveFfmpeg()}>保存 FFmpeg 设置</button></>}
 {status&&<p className="success-text">{status}</p>}<hr/><button className="quiet" onClick={onLogout}><LogOut size={16}/>退出工作室</button></>;
}

createRoot(document.getElementById("root")!).render(<Studio />);
