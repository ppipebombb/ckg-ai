"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Loader2, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { ErrorState } from "@/components/common/error-state";

type Option = { id: string; label: string };

interface OptionsResult {
  options: Option[];
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  fetchNextPage: () => void;
  error: unknown;
}

interface AsyncComboboxProps {
  value: string | undefined;
  onChange: (id: string | undefined) => void;
  useOptions: (search: string) => OptionsResult;
  selectedLabel?: string;
  placeholder?: string;
  /** Renders a static "All X" option at the top; clicking it calls onChange(undefined). */
  allOptionLabel?: string;
  disabled?: boolean;
  className?: string;
  emptyMessage?: string;
}

export function AsyncCombobox({
  value,
  onChange,
  useOptions,
  selectedLabel,
  placeholder = "Select…",
  allOptionLabel,
  disabled,
  className,
  emptyMessage = "No results.",
}: AsyncComboboxProps) {
  const [open, setOpen] = useState(false);
  const [searchRaw, setSearchRaw] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);

  const debouncedSearch = useDebouncedValue(searchRaw, 250);
  const { options, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage, error } =
    useOptions(debouncedSearch);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const itemRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    if (!open) {
      setSearchRaw("");
      setActiveIndex(-1);
    }
  }, [open]);

  useEffect(() => {
    setActiveIndex(-1);
  }, [options]);

  useEffect(() => {
    if (activeIndex >= 0) {
      itemRefs.current[activeIndex]?.scrollIntoView({ block: "nearest" });
    }
  }, [activeIndex]);

  const handleScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      if (!hasNextPage || isFetchingNextPage) return;
      const t = e.currentTarget;
      if (t.scrollHeight - (t.scrollTop + t.clientHeight) < 80) {
        fetchNextPage();
      }
    },
    [hasNextPage, isFetchingNextPage, fetchNextPage],
  );

  // When allOptionLabel is present, it occupies index 0; regular options are offset by 1.
  const allCount = allOptionLabel ? 1 : 0;
  const totalCount = allCount + options.length;

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, totalCount - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" && activeIndex >= 0) {
        e.preventDefault();
        if (allOptionLabel && activeIndex === 0) {
          onChange(undefined);
        } else {
          onChange(options[activeIndex - allCount].id);
        }
        setOpen(false);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    },
    [options, activeIndex, onChange, allOptionLabel, allCount, totalCount],
  );

  const triggerLabel =
    value != null
      ? (selectedLabel ?? options.find((o) => o.id === value)?.label ?? placeholder)
      : (allOptionLabel ?? placeholder);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={open}
          className={cn(
            "flex h-9 w-full items-center justify-between rounded-md border border-[var(--input)] bg-[var(--background)] px-3 py-2 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50",
            value == null && !allOptionLabel && "text-[var(--muted-foreground)]",
            className,
          )}
        >
          <span className="truncate">{triggerLabel}</span>
          <ChevronDown className="h-4 w-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>

      <PopoverContent
        className="p-0"
        style={{ width: "var(--radix-popover-trigger-width)" }}
        onKeyDown={handleKeyDown}
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          inputRef.current?.focus();
        }}
      >
        <div className="border-b border-[var(--border)] p-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-[var(--muted-foreground)]" />
            <Input
              ref={inputRef}
              placeholder="Search…"
              className="h-8 pl-8 text-sm"
              value={searchRaw}
              onChange={(e) => setSearchRaw(e.target.value)}
            />
          </div>
        </div>

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="max-h-[260px] overflow-y-auto"
          role="listbox"
        >
          {allOptionLabel && (
            <div
              ref={(el) => { itemRefs.current[0] = el; }}
              role="option"
              aria-selected={value == null}
              className={cn(
                "relative flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none",
                0 === activeIndex
                  ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                  : "hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]",
              )}
              onMouseEnter={() => setActiveIndex(0)}
              onClick={() => { onChange(undefined); setOpen(false); }}
            >
              <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                {value == null && <Check className="h-4 w-4" />}
              </span>
              <span className="truncate">{allOptionLabel}</span>
            </div>
          )}
          {error ? (
            <div className="p-2">
              <ErrorState error={error} />
            </div>
          ) : isLoading && options.length === 0 ? (
            <div className="flex items-center justify-center p-4 text-sm text-[var(--muted-foreground)]">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading…
            </div>
          ) : options.length === 0 ? (
            <div className="p-4 text-center text-sm text-[var(--muted-foreground)]">
              {emptyMessage}
            </div>
          ) : (
            options.map((opt, i) => (
              <div
                key={opt.id}
                ref={(el) => {
                  itemRefs.current[i + allCount] = el;
                }}
                role="option"
                aria-selected={opt.id === value}
                className={cn(
                  "relative flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none",
                  i + allCount === activeIndex
                    ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                    : "hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)]",
                )}
                onMouseEnter={() => setActiveIndex(i + allCount)}
                onClick={() => {
                  onChange(opt.id);
                  setOpen(false);
                }}
              >
                <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                  {opt.id === value && <Check className="h-4 w-4" />}
                </span>
                <span className="truncate">{opt.label}</span>
              </div>
            ))
          )}

          {isFetchingNextPage && (
            <div className="flex items-center justify-center py-2 text-sm text-[var(--muted-foreground)]">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading more…
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
