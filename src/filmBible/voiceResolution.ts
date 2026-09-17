type Value=Record<string,any>;
export function voiceSnapshot(profile:Value){return Object.fromEntries(Object.entries(profile).filter(([key])=>!['lockedVersions','defaultVersion'].includes(key)))}
export function lockedVoiceVersions(profile?:Value):Record<string,Value>{
 const versions={...profile?.lockedVersions};if(profile?.status==='locked')versions[String(profile.version)]=voiceSnapshot(profile);return versions;
}
export function effectiveVoiceProfile(profile?:Value):Value|undefined{
 if(profile?.defaultVersion===undefined||profile?.defaultVersion===null)return profile;
 const selected=lockedVoiceVersions(profile)[String(profile.defaultVersion)];
 if(!selected)throw new Error('默认音色版本不存在，请重新选择已锁定版本');return selected;
}
export function voiceCardId(document:Value,shot:Value,line:Value):string{
 const visual=document.filmBible?.visual||{},cards=visual.cards||{},versions=visual.versions||{};
 const cid=line.characterCardId||'',card=cards[cid]||{},base=card.kind==='character_state'?card.parentCardId:cid;
 if(card.kind==='character_state')return card.voiceVersion!==undefined&&card.voiceVersion!==null?cid:base;
 const choices=new Set<string>();
 for(const binding of shot.assetBindings?.characters||[]){const state=cards[versions[binding.versionId]?.cardId]||{};
  if(state.kind==='character_state'&&state.parentCardId===base&&state.voiceVersion!==undefined&&state.voiceVersion!==null)choices.add(state.id);
 }
 if(choices.size>1)throw new Error('同一镜头绑定了多个不同音色的角色状态，请明确说话状态');
 return choices.values().next().value||base||cid;
}
export function resolvedVoice(document:Value,shot:Value,line:Value):{cardId:string;profile:Value}{
 const cardId=voiceCardId(document,shot,line),card=document.filmBible?.visual?.cards?.[cardId]||{},profiles=document.filmBible?.voices?.profiles||{};
 if(card.kind==='character_state'&&card.voiceVersion!==undefined&&card.voiceVersion!==null){
  const profile=lockedVoiceVersions(profiles[card.parentCardId])[String(card.voiceVersion)];
  if(!profile)throw new Error('角色状态选择的音色版本不存在，请重新选择');return {cardId,profile};
 }
 return {cardId,profile:effectiveVoiceProfile(profiles[cardId])||{}};
}
