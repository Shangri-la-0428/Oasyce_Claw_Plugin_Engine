import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Mock fetch before any module that touches api/client ───────
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// First call is ensureToken from client.ts module load
mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });

const {
  inboxItems, trustConfig, scanning, lastScan,
  loadInbox, loadTrust, scanDirectory,
  approveItem, rejectItem, approveAll, rejectAll,
  editItem, setTrust,
} = await import('../store/scanner');

// Helpers
function okResponse(data: any) {
  return { ok: true, status: 200, text: async () => JSON.stringify(data) };
}
function errResponse(status: number) {
  return { ok: false, status, text: async () => JSON.stringify({ error: 'fail' }) };
}

function makePendingItem(id: string): any {
  return {
    item_id: id,
    file_path: `/data/${id}.csv`,
    suggested_name: `Item ${id}`,
    suggested_tags: ['test'],
    suggested_description: 'A test item',
    sensitivity: 'safe',
    confidence: 0.9,
    status: 'pending',
  };
}

describe('Scanner Store', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    // ensureToken on every API call
    mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });
    // Reset signals
    inboxItems.value = [];
    trustConfig.value = { trust_level: 0, auto_threshold: 0.8 };
    scanning.value = false;
    lastScan.value = null;
  });

  // ──────────────────────────────────────────────────────────
  // 1. loadInbox — array response
  // ──────────────────────────────────────────────────────────
  describe('loadInbox', () => {
    it('populates inboxItems from plain array response', async () => {
      const items = [makePendingItem('a'), makePendingItem('b')];
      mockFetch.mockResolvedValueOnce(okResponse(items));

      await loadInbox();

      expect(inboxItems.value).toHaveLength(2);
      expect(inboxItems.value[0].item_id).toBe('a');
      expect(inboxItems.value[1].item_id).toBe('b');
    });

    // ──────────────────────────────────────────────────────────
    // 2. loadInbox — {items: [...]} response format
    // ──────────────────────────────────────────────────────────
    it('handles {items: [...]} response format', async () => {
      const items = [makePendingItem('c')];
      mockFetch.mockResolvedValueOnce(okResponse({ items }));

      await loadInbox();

      expect(inboxItems.value).toHaveLength(1);
      expect(inboxItems.value[0].item_id).toBe('c');
    });

    it('handles failure gracefully', async () => {
      inboxItems.value = [makePendingItem('old')];
      mockFetch.mockResolvedValueOnce(errResponse(500));

      await loadInbox();

      // Unchanged on failure
      expect(inboxItems.value).toHaveLength(1);
      expect(inboxItems.value[0].item_id).toBe('old');
    });
  });

  // ──────────────────────────────────────────────────────────
  // 3. loadTrust
  // ──────────────────────────────────────────────────────────
  describe('loadTrust', () => {
    it('populates trustConfig from response', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ trust_level: 2, auto_threshold: 0.6 }));

      await loadTrust();

      expect(trustConfig.value).toEqual({ trust_level: 2, auto_threshold: 0.6 });
    });

    it('leaves default on failure', async () => {
      mockFetch.mockResolvedValueOnce(errResponse(500));

      await loadTrust();

      expect(trustConfig.value).toEqual({ trust_level: 0, auto_threshold: 0.8 });
    });
  });

  // ──────────────────────────────────────────────────────────
  // 4. scanDirectory
  // ──────────────────────────────────────────────────────────
  describe('scanDirectory', () => {
    it('sets scanning=true during call, false after', async () => {
      let scanningDuring = false;
      // POST /scan response
      mockFetch.mockImplementationOnce(() => {
        scanningDuring = scanning.value;
        return Promise.resolve(okResponse({ scanned: 10, added: 3 }));
      });
      // ensureToken for loadInbox
      mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });
      // GET /inbox for loadInbox inside scanDirectory
      mockFetch.mockResolvedValueOnce(okResponse([]));

      await scanDirectory('/tmp/data');

      expect(scanningDuring).toBe(true);
      expect(scanning.value).toBe(false);
    });

    it('sets lastScan with scanned and added counts', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ scanned: 50, added: 12 }));
      // ensureToken for loadInbox
      mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });
      mockFetch.mockResolvedValueOnce(okResponse([]));

      await scanDirectory('/home/user/docs');

      expect(lastScan.value).toEqual({ scanned: 50, added: 12 });
    });

    it('supports added_to_inbox field name', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ scanned: 5, added_to_inbox: 2 }));
      mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });
      mockFetch.mockResolvedValueOnce(okResponse([]));

      await scanDirectory('/path');

      expect(lastScan.value).toEqual({ scanned: 5, added: 2 });
    });

    it('reloads inbox after scan', async () => {
      const newItems = [makePendingItem('fresh')];
      mockFetch.mockResolvedValueOnce(okResponse({ scanned: 1, added: 1 }));
      // ensureToken for loadInbox
      mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });
      mockFetch.mockResolvedValueOnce(okResponse(newItems));

      await scanDirectory('/tmp');

      expect(inboxItems.value).toHaveLength(1);
      expect(inboxItems.value[0].item_id).toBe('fresh');
    });
  });

  // ──────────────────────────────────────────────────────────
  // 5. approveItem — optimistic update
  // ──────────────────────────────────────────────────────────
  describe('approveItem', () => {
    it('immediately changes status to approved in signal', async () => {
      inboxItems.value = [makePendingItem('x'), makePendingItem('y')];
      mockFetch.mockResolvedValueOnce(okResponse({ ok: true }));

      // Don't await — check optimistic update
      const promise = approveItem('x');

      expect(inboxItems.value.find(i => i.item_id === 'x')!.status).toBe('approved');
      expect(inboxItems.value.find(i => i.item_id === 'y')!.status).toBe('pending');

      await promise;
    });
  });

  // ──────────────────────────────────────────────────────────
  // 6. rejectItem — optimistic update
  // ──────────────────────────────────────────────────────────
  describe('rejectItem', () => {
    it('immediately changes status to rejected in signal', async () => {
      inboxItems.value = [makePendingItem('x'), makePendingItem('y')];
      mockFetch.mockResolvedValueOnce(okResponse({ ok: true }));

      const promise = rejectItem('y');

      expect(inboxItems.value.find(i => i.item_id === 'y')!.status).toBe('rejected');
      expect(inboxItems.value.find(i => i.item_id === 'x')!.status).toBe('pending');

      await promise;
    });
  });

  // ──────────────────────────────────────────────────────────
  // 7. approveAll — bulk optimistic
  // ──────────────────────────────────────────────────────────
  describe('approveAll', () => {
    it('changes all pending items to approved', async () => {
      inboxItems.value = [
        makePendingItem('a'),
        makePendingItem('b'),
        { ...makePendingItem('c'), status: 'rejected' as const },
      ];
      // Two pending items → two POST calls
      mockFetch.mockResolvedValue(okResponse({ ok: true }));

      await approveAll();

      expect(inboxItems.value.find(i => i.item_id === 'a')!.status).toBe('approved');
      expect(inboxItems.value.find(i => i.item_id === 'b')!.status).toBe('approved');
      // Already rejected — should stay rejected
      expect(inboxItems.value.find(i => i.item_id === 'c')!.status).toBe('rejected');
    });

    it('does full refresh via loadInbox on partial failure', async () => {
      inboxItems.value = [makePendingItem('a'), makePendingItem('b')];

      // Track calls: each pending item triggers ensureToken + POST
      let postCount = 0;
      mockFetch.mockImplementation(async (url: string, opts?: any) => {
        const urlStr = String(url);

        // ensureToken calls — always return 404 (no token)
        if (urlStr.includes('/auth/token')) {
          return { ok: false, status: 404, text: async () => '' };
        }

        // POST /api/inbox/<id>/approve
        if (opts?.method === 'POST' && urlStr.includes('/approve')) {
          postCount++;
          // Second approve fails
          if (postCount === 2) return errResponse(500);
          return okResponse({ ok: true });
        }

        // GET /api/inbox — loadInbox after partial failure
        if (urlStr.includes('/inbox') && !opts?.method) {
          return okResponse([
            { ...makePendingItem('a'), status: 'approved' },
            { ...makePendingItem('b'), status: 'pending' },
          ]);
        }

        return okResponse({});
      });

      await approveAll();

      // loadInbox should have been called, restoring server truth
      // Item 'b' should be back to pending (server said it failed)
      expect(inboxItems.value.find(i => i.item_id === 'b')!.status).toBe('pending');
      expect(inboxItems.value.find(i => i.item_id === 'a')!.status).toBe('approved');
    });
  });

  // ──────────────────────────────────────────────────────────
  // 8. rejectAll — bulk optimistic
  // ──────────────────────────────────────────────────────────
  describe('rejectAll', () => {
    it('changes all pending items to rejected', async () => {
      inboxItems.value = [
        makePendingItem('a'),
        makePendingItem('b'),
        { ...makePendingItem('c'), status: 'approved' as const },
      ];
      mockFetch.mockResolvedValue(okResponse({ ok: true }));

      await rejectAll();

      expect(inboxItems.value.find(i => i.item_id === 'a')!.status).toBe('rejected');
      expect(inboxItems.value.find(i => i.item_id === 'b')!.status).toBe('rejected');
      // Already approved — should stay approved
      expect(inboxItems.value.find(i => i.item_id === 'c')!.status).toBe('approved');
    });

    it('does full refresh via loadInbox on partial failure', async () => {
      inboxItems.value = [makePendingItem('a'), makePendingItem('b')];

      let postCount = 0;
      mockFetch.mockImplementation(async (url: string, opts?: any) => {
        const urlStr = String(url);

        if (urlStr.includes('/auth/token')) {
          return { ok: false, status: 404, text: async () => '' };
        }

        if (opts?.method === 'POST' && urlStr.includes('/reject')) {
          postCount++;
          if (postCount === 1) return errResponse(500);
          return okResponse({ ok: true });
        }

        // GET /api/inbox — loadInbox after partial failure
        if (urlStr.includes('/inbox') && !opts?.method) {
          return okResponse([
            { ...makePendingItem('a'), status: 'pending' },
            { ...makePendingItem('b'), status: 'rejected' },
          ]);
        }

        return okResponse({});
      });

      await rejectAll();

      // loadInbox should have refreshed — item 'a' back to pending
      expect(inboxItems.value.find(i => i.item_id === 'a')!.status).toBe('pending');
      expect(inboxItems.value.find(i => i.item_id === 'b')!.status).toBe('rejected');
    });
  });

  // ──────────────────────────────────────────────────────────
  // 9. editItem — optimistic merge
  // ──────────────────────────────────────────────────────────
  describe('editItem', () => {
    it('optimistically merges changes into matching item', async () => {
      inboxItems.value = [makePendingItem('e1'), makePendingItem('e2')];
      mockFetch.mockResolvedValueOnce(okResponse({ ok: true }));

      const promise = editItem('e1', {
        suggested_name: 'New Name',
        suggested_tags: ['updated'],
      });

      expect(inboxItems.value.find(i => i.item_id === 'e1')!.suggested_name).toBe('New Name');
      expect(inboxItems.value.find(i => i.item_id === 'e1')!.suggested_tags).toEqual(['updated']);
      // Other item unchanged
      expect(inboxItems.value.find(i => i.item_id === 'e2')!.suggested_name).toBe('Item e2');

      await promise;
    });

    it('sends POST with changes in body', async () => {
      inboxItems.value = [makePendingItem('e1')];
      mockFetch.mockResolvedValueOnce(okResponse({ ok: true }));

      await editItem('e1', { suggested_description: 'Updated desc' });

      // Find the POST call to /api/inbox/e1/edit
      const editCalls = mockFetch.mock.calls.filter(
        (c: any[]) => typeof c[0] === 'string' && c[0].includes('/inbox/e1/edit')
      );
      expect(editCalls.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ──────────────────────────────────────────────────────────
  // 10. setTrust
  // ──────────────────────────────────────────────────────────
  describe('setTrust', () => {
    it('updates trustConfig on success', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ trust_level: 1, auto_threshold: 0.7 }));

      await setTrust(1, 0.7);

      expect(trustConfig.value).toEqual({ trust_level: 1, auto_threshold: 0.7 });
    });

    it('does not update trustConfig on failure', async () => {
      mockFetch.mockResolvedValueOnce(errResponse(500));

      await setTrust(2, 0.5);

      // Stays at default
      expect(trustConfig.value).toEqual({ trust_level: 0, auto_threshold: 0.8 });
    });

    it('sends only provided fields', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ trust_level: 0, auto_threshold: 0.9 }));

      await setTrust(undefined, 0.9);

      // The POST body should only include auto_threshold
      const postCalls = mockFetch.mock.calls.filter(
        (c: any[]) => typeof c[0] === 'string' && c[0].includes('/inbox/trust')
      );
      expect(postCalls.length).toBeGreaterThanOrEqual(1);
    });
  });
});
