import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { MessageSquarePlus } from 'lucide-react';
import { v4 as uuid } from 'uuid';
import { forecastKeys } from '@/api/forecast/hooks';
import type { MessageResponse } from '@/api/chat/types';
import { ChatProvider, useChatContext } from '@/components/block/chat';
import { useChatList } from '@/components/block/chat/hooks/use-chat-list';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useForecastUi } from '@/lib/forecast/store';
import { ChatImplementation } from '@/pages/ChatPage';

const CHAT_ID_KEY = 'forecast_chat_id';

const greeting: MessageResponse[] = [
  {
    id: uuid(),
    role: 'assistant',
    content: {
      format: 2,
      parts: [
        {
          type: 'text',
          text:
            '長期需要予測・シナリオ分析エージェントです。例えば次のように話しかけてください。\n\n' +
            '- ベースシナリオで2050年までの見通しを見せて\n' +
            '- 脱炭素加速だと鉱山機械はどう変わる？\n' +
            '- アフリカの伸びが大きすぎる気がする。なぜ？',
        },
      ],
    },
    createdAt: new Date(),
    type: 'initial',
  },
];

function readChatId(): string {
  try {
    return localStorage.getItem(CHAT_ID_KEY) ?? '';
  } catch {
    return '';
  }
}

/**
 * Registers the chat's send function for page buttons and refreshes every
 * forecast query whenever the agent finishes a turn (tool results land in the
 * shared store, so the pages pick them up right away).
 */
function ChatBridge() {
  const { sendTextMessage, isAgentRunning } = useChatContext();
  const registerChat = useForecastUi(s => s.registerChat);
  const queryClient = useQueryClient();
  const wasRunning = useRef(false);

  useEffect(() => {
    registerChat(sendTextMessage, isAgentRunning);
  }, [sendTextMessage, isAgentRunning, registerChat]);

  useEffect(() => () => registerChat(null, false), [registerChat]);

  useEffect(() => {
    if (!isAgentRunning) {
      if (wasRunning.current) {
        void queryClient.invalidateQueries({ queryKey: forecastKeys.all });
      }
      wasRunning.current = false;
      return;
    }
    wasRunning.current = true;
    // tools finish before the answer does: refresh while the agent is still talking
    const t = setInterval(
      () => void queryClient.invalidateQueries({ queryKey: forecastKeys.all }),
      4000
    );
    return () => clearInterval(t);
  }, [isAgentRunning, queryClient]);

  return null;
}

export function ChatPanel() {
  const [chatId, setChatIdState] = useState<string>(readChatId);
  const setChatId = (id: string) => {
    setChatIdState(id);
    try {
      localStorage.setItem(CHAT_ID_KEY, id);
    } catch {
      /* per-browser convenience only */
    }
  };
  const { hasChat, isNewChat, chats, isLoadingChats, addChatHandler, refetchChats } = useChatList({
    chatId,
    setChatId,
  });

  useLayoutEffect(() => {
    if (isLoadingChats || !chats || chats.find(c => c.id === chatId)) return;
    if (chatId && isNewChat) return;
    if (!chats.length) addChatHandler();
    else setChatId(chats[0].id);
  }, [chats, isLoadingChats, chatId, isNewChat]);

  return (
    <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-border bg-background">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <div>
          <div className="text-sm font-semibold">エージェント</div>
          <div className="text-xs text-muted-foreground">操作結果は各ページに反映されます</div>
        </div>
        <Button variant="ghost" size="sm" onClick={addChatHandler} title="新しい会話">
          <MessageSquarePlus className="size-4" />
          <span className="text-xs">新しい会話</span>
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        {isLoadingChats || !chatId || !hasChat ? (
          <div className="space-y-3 p-4">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : (
          <ChatProvider
            key={chatId}
            chatId={chatId}
            runInBackground={true}
            isNewChat={isNewChat}
            refetchChats={refetchChats}
          >
            <ChatBridge />
            <ChatImplementation chatId={chatId} greeting={greeting} />
          </ChatProvider>
        )}
      </div>
    </aside>
  );
}
