/** Per-object save state. A remote snapshot never replaces an unsaved draft. */
export type ObjectRow = {
  id: string;
  kind: string;
  revision: number;
  assignment_epoch: number;
  assignee_id: string | null;
  content: Record<string, any>;
  [key: string]: any;
};
export type SaveState = 'saved' | 'dirty' | 'saving' | 'conflict' | 'error';
export type ObjectDraft = {
  base: ObjectRow;
  content: Record<string, any>;
  state: SaveState;
  remote?: ObjectRow;
  error?: string;
  serial: number;
  flight?: number;
};
export type SaveTicket = {
  projectId: string;
  generation: number;
  id: string;
  flight: number;
  serial: number;
  expected_revision: number;
  assignment_epoch: number;
  content: Record<string, any>;
};

const clone = <T>(value: T): T => structuredClone(value);

export function equalContent(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length &&
      left.every((value, index) => equalContent(value, right[index]));
  }
  const a = left as Record<string, unknown>, b = right as Record<string, unknown>;
  const keys = Object.keys(a).filter(key => a[key] !== undefined);
  return keys.length === Object.keys(b).filter(key => b[key] !== undefined).length &&
    keys.every(key => equalContent(a[key], b[key]));
}

export class ObjectDrafts {
  projectId = '';
  generation = 0;
  sequence = 0;
  entries = new Map<string, ObjectDraft>();

  get unsaved() {
    return [...this.entries.values()].some(entry => entry.state !== 'saved');
  }

  open(projectId: string, rows: ObjectRow[], discard = false) {
    if (this.unsaved && !discard) throw new Error('仍有未保存对象；请保存、解决冲突或明确放弃草稿');
    this.generation += 1;
    this.projectId = projectId;
    this.entries.clear();
    rows.forEach(row => this.entries.set(row.id, this.clean(row)));
  }

  private clean(row: ObjectRow): ObjectDraft {
    return {base: clone(row), content: clone(row.content), state: 'saved', serial: 0};
  }

  edit(id: string, content: Record<string, any>) {
    const entry = this.require(id);
    entry.content = clone(content);
    entry.serial += 1;
    if (entry.state === 'conflict') return; // Explicit comparison is required.
    entry.state = entry.flight ? 'saving' : equalContent(content, entry.base.content) ? 'saved' : 'dirty';
    entry.error = undefined;
  }

  remote(projectId: string, generation: number, row: ObjectRow): boolean {
    if (projectId !== this.projectId || generation !== this.generation) return false;
    const entry = this.entries.get(row.id);
    if (!entry) {
      this.entries.set(row.id, this.clean(row));
      return true;
    }
    if (row.revision < entry.base.revision) return false;
    if (entry.remote && row.revision < entry.remote.revision) return false;
    if (entry.state !== 'saved' || entry.flight) {
      if (row.revision !== entry.base.revision || row.assignment_epoch !== entry.base.assignment_epoch) {
        entry.remote = clone(row);
        if (!entry.flight) {
          entry.state = 'conflict';
          entry.error = '远端对象已更新；本地草稿保留，请比较后明确处理';
        }
      }
      return false;
    }
    this.entries.set(row.id, this.clean(row));
    return true;
  }

  begin(id: string): SaveTicket | null {
    const entry = this.require(id);
    // A timer cannot resubmit a conflicted payload with a newer revision.
    if (entry.flight || !['dirty', 'error'].includes(entry.state)) return null;
    const flight = ++this.sequence;
    entry.flight = flight;
    entry.state = 'saving';
    return {projectId: this.projectId, generation: this.generation, id, flight, serial: entry.serial,
      expected_revision: entry.base.revision, assignment_epoch: entry.base.assignment_epoch,
      content: clone(entry.content)};
  }

  acknowledge(ticket: SaveTicket, row: ObjectRow): boolean {
    const entry = this.match(ticket);
    if (!entry || row.id !== ticket.id) return false;
    const observed=entry.remote;
    entry.flight = undefined;
    entry.base = clone(row);
    entry.remote = undefined;
    entry.error = undefined;
    if (entry.serial === ticket.serial) entry.content = clone(row.content);
    entry.state = equalContent(entry.content, row.content) ? 'saved' : 'dirty';
    // A newer SSE/read may arrive before the response to our earlier save.
    // Keep the acknowledged body/version paired until the user explicitly
    // compares the newer snapshot. Advancing only this draft would leave the
    // host document and client baseline at the older body.
    if(observed&&(observed.revision>row.revision||observed.assignment_epoch>row.assignment_epoch)){
      entry.remote=observed;
      entry.state='conflict';
      entry.error='本次保存已提交，但远端对象已有更新；本地草稿保留，请比较后明确处理';
    }
    return true;
  }

  reject(ticket: SaveTicket, status: number, message: string): boolean {
    const entry = this.match(ticket);
    if (!entry) return false;
    entry.flight = undefined;
    entry.state = status === 409 ? 'conflict' : 'error';
    entry.error = message;
    return true;
  }

  /** Only an explicit UI action may reload/discard or compare-and-reapply. */
  resolve(id: string, latest: ObjectRow, choice: 'discard' | 'keep-draft') {
    const entry = this.require(id);
    if (entry.flight) throw new Error('对象仍在保存中');
    if (latest.id !== id) throw new Error('冲突对象不匹配');
    if (choice === 'keep-draft' && latest.assignment_epoch !== entry.base.assignment_epoch) {
      throw new Error('负责人已变更；不能复用旧编辑凭据，请重新领取并编辑');
    }
    const next = this.clean(latest);
    if (choice === 'keep-draft') {
      next.content = clone(entry.content);
      next.serial = entry.serial + 1;
      next.state = equalContent(next.content, latest.content) ? 'saved' : 'dirty';
    }
    this.entries.set(id, next);
  }

  private match(ticket: SaveTicket) {
    if (ticket.projectId !== this.projectId || ticket.generation !== this.generation) return null;
    const entry = this.entries.get(ticket.id);
    return entry?.flight === ticket.flight ? entry : null;
  }

  private require(id: string) {
    const entry = this.entries.get(id);
    if (!entry) throw new Error('对象尚未载入');
    return entry;
  }
}
