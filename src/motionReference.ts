type Value=Record<string,any>;
export const videoModeLabels:Record<string,string>={legacy:'兼容历史',multimodal:'多模态参考',first_frame:'严格首帧',first_last_frame:'严格首尾帧'};
export function videoGenerationMode(document:Value,shot:Value){return shot.videoReferenceMode||document.videoReferenceMode||'legacy'}
export function motionCharacters(document:Value,shot:Value):Value[]{
 const visual=document.filmBible?.visual||{},items=new Map<string,Value>();
 for(const binding of shot.assetBindings?.characters||[]){
  let card=visual.cards?.[visual.versions?.[binding.versionId]?.cardId];
  const seen=new Set<string>();
  while(card&&!card.deletedAt&&!seen.has(card.id)){items.set(card.id,card);seen.add(card.id);card=visual.cards?.[card.parentCardId]}
 }
 return [...items.values()];
}
