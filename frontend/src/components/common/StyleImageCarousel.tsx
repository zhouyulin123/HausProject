import {
  AnimatePresence,
  motion,
  useReducedMotion,
} from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  useCallback,
  useEffect,
  useState,
  type FocusEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import {
  getNextSlideIndex,
  getPreviousSlideIndex,
} from "@/lib/carousel";

interface StyleImageCarouselProps {
  images: string[];
  label: string;
  className?: string;
  autoPlay?: boolean;
  intervalMs?: number;
  onOpen?: () => void;
  caption?: ReactNode;
  topRight?: ReactNode;
}

export default function StyleImageCarousel({
  images,
  label,
  className = "h-40",
  autoPlay = true,
  intervalMs = 5200,
  onOpen,
  caption,
  topRight,
}: StyleImageCarouselProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const reduceMotion = useReducedMotion();
  const slideCount = images.length;

  useEffect(() => {
    if (activeIndex >= slideCount) setActiveIndex(0);
  }, [activeIndex, slideCount]);

  const showNext = useCallback(() => {
    setActiveIndex((current) => getNextSlideIndex(current, slideCount));
  }, [slideCount]);

  const showPrevious = useCallback(() => {
    setActiveIndex((current) => getPreviousSlideIndex(current, slideCount));
  }, [slideCount]);

  useEffect(() => {
    if (!autoPlay || isPaused || reduceMotion || slideCount <= 1) return;
    const timer = window.setInterval(showNext, intervalMs);
    return () => window.clearInterval(timer);
  }, [autoPlay, intervalMs, isPaused, reduceMotion, showNext, slideCount]);

  const handleControlClick = (
    event: MouseEvent<HTMLButtonElement>,
    action: () => void,
  ) => {
    event.stopPropagation();
    action();
  };

  const handleBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setIsPaused(false);
    }
  };

  if (slideCount === 0) {
    return (
      <div
        className={`relative overflow-hidden bg-gradient-to-br from-stone-100 to-stone-300 ${className}`}
        aria-label={`${label}案例图片暂不可用`}
      >
        {caption && (
          <div className="absolute right-4 bottom-4 left-4 z-20">{caption}</div>
        )}
      </div>
    );
  }

  return (
    <div
      role="region"
      aria-roledescription="carousel"
      aria-label={`${label}案例图片`}
      className={`group/carousel relative overflow-hidden bg-stone-200 ${className}`}
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => setIsPaused(false)}
      onFocusCapture={() => setIsPaused(true)}
      onBlurCapture={handleBlur}
    >
      <AnimatePresence initial={false} mode="popLayout">
        <motion.img
          key={images[activeIndex]}
          src={images[activeIndex]}
          alt={`${label}案例效果图 ${activeIndex + 1}`}
          loading="lazy"
          decoding="async"
          draggable={false}
          initial={reduceMotion ? false : { opacity: 0, scale: 1.025 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={reduceMotion ? undefined : { opacity: 0 }}
          transition={{ duration: reduceMotion ? 0 : 0.45, ease: "easeOut" }}
          className="absolute inset-0 h-full w-full object-cover"
        />
      </AnimatePresence>

      <div className="pointer-events-none absolute inset-0 z-10 bg-gradient-to-t from-stone-950/55 via-transparent to-stone-950/10" />

      {onOpen && (
        <button
          type="button"
          onClick={onOpen}
          className="absolute inset-0 z-20 cursor-zoom-in"
          aria-label={`查看${label}风格详情`}
        />
      )}

      {topRight && (
        <div className="absolute top-3 right-3 z-40">{topRight}</div>
      )}

      {slideCount > 1 && (
        <>
          <button
            type="button"
            onClick={(event) => handleControlClick(event, showPrevious)}
            className="absolute top-1/2 left-3 z-40 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-stone-950/25 text-white opacity-100 backdrop-blur-md transition hover:bg-stone-950/45 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:opacity-0 sm:group-hover/carousel:opacity-100 sm:group-focus-within/carousel:opacity-100"
            aria-label={`${label}上一张案例图`}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={(event) => handleControlClick(event, showNext)}
            className="absolute top-1/2 right-3 z-40 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-stone-950/25 text-white opacity-100 backdrop-blur-md transition hover:bg-stone-950/45 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:opacity-0 sm:group-hover/carousel:opacity-100 sm:group-focus-within/carousel:opacity-100"
            aria-label={`${label}下一张案例图`}
          >
            <ChevronRight className="h-4 w-4" />
          </button>

          <div className="absolute right-0 bottom-3 left-0 z-40 flex justify-center gap-1.5">
            {images.map((image, index) => (
              <button
                key={image}
                type="button"
                onClick={(event) =>
                  handleControlClick(event, () => setActiveIndex(index))
                }
                className={`h-1.5 rounded-full shadow-sm transition-all ${
                  activeIndex === index
                    ? "w-5 bg-white"
                    : "w-1.5 bg-white/55 hover:bg-white/80"
                }`}
                aria-label={`显示${label}第 ${index + 1} 张案例图`}
                aria-current={activeIndex === index ? "true" : undefined}
              />
            ))}
          </div>
        </>
      )}

      {caption && (
        <div className="pointer-events-none absolute right-4 bottom-8 left-4 z-30">
          {caption}
        </div>
      )}
    </div>
  );
}
