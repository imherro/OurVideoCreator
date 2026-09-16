export type CharacterDialogueRow = {
  id: string;
  shotId: string;
  shotOrder: number;
  text: string;
  emotion: string;
  asset?: Record<string, any>;
  job?: Record<string, any>;
  status: "missing" | "queued" | "running" | "failed" | "interrupted" | "syncing" | "ready";
};

export function projectCharacterDialogueRows({
  shots,
  assets,
  jobs,
  cardId,
  voiceVersion,
}: {
  shots: Array<Record<string, any>>;
  assets: Array<Record<string, any>>;
  jobs: Array<Record<string, any>>;
  cardId: string;
  voiceVersion?: number;
}): CharacterDialogueRow[] {
  return shots.flatMap((shot, shotIndex) =>
    (Array.isArray(shot.dialogues) ? shot.dialogues : [])
      .filter((dialogue: Record<string, any>) => dialogue.characterCardId === cardId)
      .map((dialogue: Record<string, any>) => {
        const matchesVersion = (descriptor: Record<string, any> | undefined) =>
          descriptor?.id === dialogue.id && descriptor?.voiceVersion === voiceVersion;
        const asset = assets.find((candidate) =>
          candidate.kind === "audio" && candidate.id === dialogue.audioAssetId && dialogue.audioVoiceVersion === voiceVersion
            && candidate.metadata?.input?.dialogue?.text === dialogue.text && matchesVersion(candidate.metadata?.input?.dialogue),
        );
        const job = jobs.find((candidate) => matchesVersion(candidate.input?.dialogue));
        const jobStatus = String(job?.status || "");
        const status: CharacterDialogueRow["status"] = asset
          ? "ready"
          : jobStatus === "queued" || jobStatus === "running" || jobStatus === "failed" || jobStatus === "interrupted"
            ? jobStatus
            : jobStatus === "succeeded"
              ? "syncing"
              : "missing";
        return {
          id: String(dialogue.id),
          shotId: String(shot.id || `shot-${shotIndex + 1}`),
          shotOrder: Number(shot.order) || shotIndex + 1,
          text: String(dialogue.text || ""),
          emotion: String(dialogue.emotion || ""),
          asset,
          job,
          status,
        };
      }),
  );
}

