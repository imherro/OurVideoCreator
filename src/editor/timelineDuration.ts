import type {ProjectJSON} from '@twick/timeline';

const positive = (value: unknown) => Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : 0;
export function timelineContentDuration(timeline?: ProjectJSON | null) {
  return Math.max(0, ...(timeline?.tracks || []).flatMap(track => track.elements.map(element => positive(element.e))));
}
export function timelineWorkspaceDuration(timeline: ProjectJSON | null | undefined, projectDuration: number) {
  return Math.max(5, positive(projectDuration), positive(timeline?.metadata?.custom?.timelineDuration), timelineContentDuration(timeline));
}
export function withTimelineWorkspaceDuration(timeline: ProjectJSON, duration: number, projectDuration: number): ProjectJSON {
  return {...timeline, metadata: {...timeline.metadata, custom: {...timeline.metadata?.custom,
    timelineDuration: Math.max(5, positive(projectDuration), positive(duration), timelineContentDuration(timeline))}}};
}
