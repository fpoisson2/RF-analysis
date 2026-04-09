import React, { useEffect, useRef } from 'react';
import { ChevronDown, ChevronUp, Terminal } from 'lucide-react';
import { Locale, t } from '../i18n';

interface ConsoleProps {
  messages: string[];
  isOpen: boolean;
  onToggle: () => void;
  locale: Locale;
}

export function Console({ messages, isOpen, onToggle, locale }: ConsoleProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className={`border-t border-gray-800 bg-surface-1 transition-all duration-300 ${isOpen ? 'h-48' : 'h-8'}`}>
      <button
        onClick={onToggle}
        className="w-full h-8 flex items-center justify-between px-3 hover:bg-surface-2 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-xs font-medium text-gray-400">{t('console.title', locale)}</span>
          <span className="text-[10px] text-gray-600 bg-surface-3 px-1.5 rounded">{messages.length}</span>
        </div>
        {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-gray-500" /> : <ChevronUp className="w-3.5 h-3.5 text-gray-500" />}
      </button>

      {isOpen && (
        <div ref={scrollRef} className="h-[calc(100%-2rem)] overflow-y-auto px-3 pb-2">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`text-xs font-mono leading-5 ${
                msg.includes('ERROR') || msg.includes('ERREUR')
                  ? 'text-red-400'
                  : msg.includes('complete') || msg.includes('terminé')
                  ? 'text-brand-400'
                  : 'text-gray-400'
              }`}
            >
              {msg}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
