import type { ProjectJSON } from '@twick/timeline';
import { equalContent } from '../objectDrafts.ts';

/** Bridge the already draft-protected host document and Twick's live instance.
 * A host snapshot is not an editor mutation to publish back to the server.
 */
export class TimelineInputSync {
  private input: ProjectJSON;
  private published: ProjectJSON;

  constructor(initial: ProjectJSON, normalized: ProjectJSON = initial) {
    this.input = structuredClone(initial);
    this.published = structuredClone(normalized);
  }

  update(input: ProjectJSON, read: () => ProjectJSON, load: (value: ProjectJSON) => void): ProjectJSON | null {
    const current = read();
    if (!equalContent(input, this.input)) {
      this.input = structuredClone(input);
      // A local onChange acknowledgement must not reset undo/selection/player.
      if (!equalContent(input, this.published) && !equalContent(input, current)) {
        load(structuredClone(input));
        // Twick normalizes its JSON during load. Treat that normalized value as
        // the baseline too, so receiving a remote object never echoes a save.
        this.published = structuredClone(read());
        return null;
      }
    }
    if (equalContent(current, this.published)) return null;
    this.published = structuredClone(current);
    return current;
  }
}
