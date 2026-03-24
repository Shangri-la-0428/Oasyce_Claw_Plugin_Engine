/**
 * useChain — React hook for Cosmos chain connectivity.
 *
 * Checks if the Oasyce Cosmos chain is reachable via REST.
 * Exposes connection state, node info, and latest block info.
 * Falls back gracefully — when the chain is unavailable the
 * existing Python backend (localhost:8000) should be used instead.
 *
 * Uses exponential backoff: 15s → 30s → 60s → … → 5min cap.
 * Resets to 15s on successful connection.
 */
import { useState, useEffect, useCallback, useRef } from 'preact/hooks';
import {
  isChainAvailable,
  getNodeInfo,
  getLatestBlock,
  type NodeInfo,
  type Block,
} from '../api/chain';

export interface ChainState {
  /** Whether we are currently checking connectivity */
  loading: boolean;
  /** True if the Cosmos chain REST API responded successfully */
  isChainConnected: boolean;
  /** Node info from the chain (null if not connected) */
  chainInfo: NodeInfo | null;
  /** Latest block from the chain (null if not connected) */
  latestBlock: Block | null;
  /** Chain ID extracted from node info or block header */
  chainId: string | null;
  /** Latest block height as a number */
  blockHeight: number | null;
  /** Error message if the last check failed */
  error: string | null;
  /** Manually re-check chain connectivity */
  refresh: () => Promise<void>;
}

const POLL_BASE_MS = 15_000;
const POLL_MAX_MS = 300_000; // 5 min cap

export function useChain(autoPoll = true): ChainState {
  const [loading, setLoading] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [chainInfo, setChainInfo] = useState<NodeInfo | null>(null);
  const [latestBlock, setLatestBlock] = useState<Block | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const backoffRef = useRef(POLL_BASE_MS);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const check = useCallback(async () => {
    setLoading(true);
    setError(null);
    let connected = false;
    try {
      const available = await isChainAvailable();
      if (!mountedRef.current) return;

      if (!available) {
        setIsConnected(false);
        setChainInfo(null);
        setLatestBlock(null);
        setLoading(false);
        return;
      }

      const [info, block] = await Promise.all([
        getNodeInfo().catch(() => null),
        getLatestBlock().catch(() => null),
      ]);
      if (!mountedRef.current) return;

      connected = true;
      setIsConnected(true);
      setChainInfo(info);
      setLatestBlock(block);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setIsConnected(false);
      setChainInfo(null);
      setLatestBlock(null);
      setError(e instanceof Error ? e.message : 'Chain check failed');
    } finally {
      if (mountedRef.current) {
        setLoading(false);
        // Schedule next poll with backoff
        if (autoPoll) {
          backoffRef.current = connected
            ? POLL_BASE_MS
            : Math.min(backoffRef.current * 2, POLL_MAX_MS);
          timerRef.current = setTimeout(check, backoffRef.current);
        }
      }
    }
  }, [autoPoll]);

  useEffect(() => {
    mountedRef.current = true;
    check();

    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [check]);

  const chainId =
    chainInfo?.default_node_info?.network ??
    latestBlock?.block?.header?.chain_id ??
    null;

  const blockHeight = latestBlock?.block?.header?.height
    ? Number(latestBlock.block.header.height)
    : null;

  return {
    loading,
    isChainConnected: isConnected,
    chainInfo,
    latestBlock,
    chainId,
    blockHeight,
    error,
    refresh: check,
  };
}
