/**
 * useChain — React hook for Cosmos chain connectivity.
 *
 * Checks if the Oasyce Cosmos chain is reachable via REST.
 * Exposes connection state, node info, and latest block info.
 * Falls back gracefully — when the chain is unavailable the
 * existing Python backend (localhost:8000) should be used instead.
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

/** How often to auto-refresh chain info (ms). */
const POLL_INTERVAL_MS = 15_000;

export function useChain(autoPoll = true): ChainState {
  const [loading, setLoading] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [chainInfo, setChainInfo] = useState<NodeInfo | null>(null);
  const [latestBlock, setLatestBlock] = useState<Block | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const check = useCallback(async () => {
    setLoading(true);
    setError(null);
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

      // Chain is up — fetch details in parallel.
      const [info, block] = await Promise.all([
        getNodeInfo().catch(() => null),
        getLatestBlock().catch(() => null),
      ]);
      if (!mountedRef.current) return;

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
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  // Initial check + polling
  useEffect(() => {
    mountedRef.current = true;
    check();

    let timer: ReturnType<typeof setInterval> | null = null;
    if (autoPoll) {
      timer = setInterval(check, POLL_INTERVAL_MS);
    }

    return () => {
      mountedRef.current = false;
      if (timer) clearInterval(timer);
    };
  }, [check, autoPoll]);

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
