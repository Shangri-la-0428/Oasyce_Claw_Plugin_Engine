import { describe, it, expect } from 'vitest';
import { mask, maskIdShort, maskIdLong, maskOwner, fmtPrice, safeNum, safePct } from '../utils';

describe('mask', () => {
  it('returns -- for null/undefined', () => {
    expect(mask(null)).toBe('--');
    expect(mask(undefined)).toBe('--');
    expect(mask('')).toBe('--');
  });

  it('returns full string if shorter than head', () => {
    expect(mask('abc', 8)).toBe('abc');
  });

  it('truncates long strings with dots', () => {
    const id = 'abcdef1234567890abcdef';
    expect(mask(id, 8)).toBe('abcdef12••••');
  });

  it('shows head…tail when tail > 0', () => {
    const id = 'abcdef1234567890abcdef';
    expect(mask(id, 6, 4)).toBe('abcdef…cdef');
  });
});

describe('maskIdShort', () => {
  it('masks to 8 chars', () => {
    expect(maskIdShort('OAS_1033E7A0DEADBEEF')).toBe('OAS_1033••••');
  });
});

describe('maskIdLong', () => {
  it('masks to 16 chars', () => {
    const long = 'abcdef1234567890abcdef1234567890';
    expect(maskIdLong(long)).toBe('abcdef1234567890••••');
  });
});

describe('maskOwner', () => {
  it('masks to 6 chars', () => {
    expect(maskOwner('alice_long_name_here')).toBe('alice_••••');
  });
});

describe('fmtPrice', () => {
  it('returns -- for null/undefined/NaN/Infinity', () => {
    expect(fmtPrice(null)).toBe('--');
    expect(fmtPrice(undefined)).toBe('--');
    expect(fmtPrice(NaN)).toBe('--');
    expect(fmtPrice(Infinity)).toBe('--');
  });

  it('formats zero', () => {
    expect(fmtPrice(0)).toBe('0.00');
  });

  it('formats >= 1 with 2 decimals', () => {
    expect(fmtPrice(1.5)).toBe('1.50');
    expect(fmtPrice(123.456)).toBe('123.46');
  });

  it('formats < 1 with 4 decimals', () => {
    expect(fmtPrice(0.1234)).toBe('0.1234');
    expect(fmtPrice(0.0001)).toBe('0.0001');
  });
});

describe('safeNum', () => {
  it('returns -- for null/undefined/NaN', () => {
    expect(safeNum(null)).toBe('--');
    expect(safeNum(undefined)).toBe('--');
    expect(safeNum(NaN)).toBe('--');
  });

  it('formats with default 2 decimals', () => {
    expect(safeNum(3.14159)).toBe('3.14');
  });

  it('respects custom decimals', () => {
    expect(safeNum(3.14159, 0)).toBe('3');
    expect(safeNum(3.14159, 4)).toBe('3.1416');
  });
});

describe('safePct', () => {
  it('returns -- for null/undefined/NaN', () => {
    expect(safePct(null)).toBe('--');
    expect(safePct(undefined)).toBe('--');
  });

  it('converts fraction to percentage', () => {
    expect(safePct(0.95)).toBe('95.0%');
    expect(safePct(1.0)).toBe('100.0%');
    expect(safePct(0)).toBe('0.0%');
  });

  it('respects custom decimals', () => {
    expect(safePct(0.9567, 2)).toBe('95.67%');
  });
});
