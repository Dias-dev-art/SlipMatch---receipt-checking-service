"use client";

// Chats the AI handed to the owner (complaints, refunds). The owner reads the conversation,
// answers the customer (sent through the Telegram bot, signed with the shop's name) or gives
// the chat back to the AI.

import { zodResolver } from "@hookform/resolvers/zod";
import { Bot, MessageCircleWarning, Send } from "lucide-react";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { CustomerContact } from "@/components/orders/order-parts";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  useAllConversations,
  useChatsNeedingOwner,
  useConversationMessages,
  useReplyToConversation,
  useResumeAi,
} from "@/hooks/use-conversations";
import { customerHandle, customerName, formatRelative, formatTime } from "@/lib/format";
import { t } from "@/lib/strings";
import type { ConversationMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

const c = t.chat;

/** null = closed, "list" = chats needing the owner, otherwise a conversation id. */
type View = null | "list" | string;

const ChatContext = createContext<{ openChat: (view: Exclude<View, null>) => void }>({
  openChat: () => {},
});

export function useChatPanel() {
  return useContext(ChatContext);
}

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [view, setView] = useState<View>(null);
  // the chat the owner replied in while the panel was open: closing hands it back to the AI
  // (seen live: after the owner left, the AI stayed silent for the whole pause)
  const [repliedIn, setRepliedIn] = useState<string | null>(null);
  const resume = useResumeAi();

  const close = () => {
    if (repliedIn) resume.mutate(repliedIn);
    setRepliedIn(null);
    setView(null);
  };

  return (
    <ChatContext.Provider value={{ openChat: setView }}>
      {children}
      <Sheet open={view !== null} onOpenChange={(open) => !open && close()}>
        <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
          {view === "list" ? (
            <ChatList onOpen={setView} />
          ) : view !== null ? (
            <ChatView
              id={view}
              onReplied={() => setRepliedIn(view)}
              onResumed={() => {
                setRepliedIn(null);
                setView(null);
              }}
            />
          ) : null}
        </SheetContent>
      </Sheet>
    </ChatContext.Provider>
  );
}

/** "2 chats need you" in the sidebar / header; hidden when there are none. */
export function ChatsButton({ className }: { className?: string }) {
  const { data: chats } = useChatsNeedingOwner();
  const { openChat } = useChatPanel();
  if (!chats?.length) return null;
  return (
    <Button
      variant="outline"
      size="sm"
      className={cn("border-status-check/50 bg-status-check-soft text-status-check", className)}
      onClick={() => openChat(chats.length === 1 ? chats[0].id : "list")}
    >
      <MessageCircleWarning />
      {t.handoff.button(chats.length)}
    </Button>
  );
}

function ChatList({ onOpen }: { onOpen: (id: string) => void }) {
  const { data: chats, isPending } = useChatsNeedingOwner();
  return (
    <>
      <SheetHeader className="border-b">
        <SheetTitle>{t.handoff.title}</SheetTitle>
        <SheetDescription>{t.handoff.body}</SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-2 overflow-y-auto p-4">
        {isPending && <Skeleton className="h-16 w-full" />}
        {chats?.length === 0 && <p className="text-sm text-muted-foreground">{c.noChats}</p>}
        {chats?.map((chat) => (
          <button
            key={chat.id}
            type="button"
            onClick={() => onOpen(chat.id)}
            className="rounded-lg border p-3 text-left transition-colors hover:bg-muted/50"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate font-medium">{customerName(chat.customer)}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {formatRelative(chat.handoff_at ?? chat.last_customer_message_at)}
              </span>
            </div>
            {chat.handoff_reason && (
              <p className="mt-1 truncate text-xs text-muted-foreground">{chat.handoff_reason}</p>
            )}
          </button>
        ))}
      </div>
    </>
  );
}

const replySchema = z.object({
  text: z.string().trim().min(1, t.auth.required).max(1000, c.tooLong),
});

function ChatView({
  id,
  onReplied,
  onResumed,
}: {
  id: string;
  onReplied: () => void;
  onResumed: () => void;
}) {
  const { data: conversations } = useAllConversations();
  const conversation = conversations?.find((conv) => conv.id === id);
  const { data: messages, isPending, isError } = useConversationMessages(id);
  const reply = useReplyToConversation(id);
  const resume = useResumeAi();
  const bottomRef = useRef<HTMLDivElement>(null);
  const form = useForm<z.infer<typeof replySchema>>({
    resolver: zodResolver(replySchema),
    defaultValues: { text: "" },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages?.length]);

  const onSubmit = form.handleSubmit(async ({ text }) => {
    const sent = await reply.mutateAsync(text).catch(() => null);
    if (sent) {
      form.reset({ text: "" });
      onReplied();
    }
  });

  // only an owner reply sets ai_paused_until; Resume AI clears it
  const paused = Boolean(conversation?.ai_paused_until) && !conversation?.needs_owner;

  return (
    <>
      <SheetHeader className="border-b">
        <SheetTitle>{conversation ? customerName(conversation.customer) : c.title}</SheetTitle>
        <SheetDescription className="flex flex-col gap-1.5">
          {conversation && customerHandle(conversation.customer)}
          {conversation?.handoff_reason && (
            <span>
              {c.reason}: <span className="text-foreground">{conversation.handoff_reason}</span>
            </span>
          )}
        </SheetDescription>
        {conversation && <CustomerContact customer={conversation.customer} className="pt-1" />}
      </SheetHeader>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2 p-4">
          {isPending && <Skeleton className="h-24 w-full" />}
          {isError && <p className="text-sm text-danger">{c.loadError}</p>}
          {messages?.length === 0 && <p className="text-sm text-muted-foreground">{c.empty}</p>}
          {messages?.map((message) => <Bubble key={message.id} message={message} />)}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-2 border-t p-4">
        {paused && <p className="text-xs text-muted-foreground">{c.paused}</p>}
        <Textarea
          rows={3}
          placeholder={c.placeholder}
          aria-invalid={Boolean(form.formState.errors.text)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void onSubmit();
          }}
          {...form.register("text")}
        />
        {form.formState.errors.text ? (
          <p className="text-xs text-danger">{form.formState.errors.text.message}</p>
        ) : (
          <p className="text-xs text-muted-foreground">{c.hint}</p>
        )}
        <div className="flex justify-between gap-2">
          <Button
            type="button"
            variant="ghost"
            disabled={resume.isPending}
            onClick={() => resume.mutate(id, { onSuccess: onResumed })}
          >
            <Bot />
            {t.handoff.resume}
          </Button>
          <Button type="submit" disabled={reply.isPending}>
            <Send />
            {reply.isPending ? c.sending : c.send}
          </Button>
        </div>
      </form>
    </>
  );
}

function Bubble({ message }: { message: ConversationMessage }) {
  const fromCustomer = message.direction === "in";
  if (!message.body) return null;
  return (
    <div className={cn("flex flex-col gap-0.5", fromCustomer ? "items-start" : "items-end")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-line",
          fromCustomer && "rounded-bl-sm bg-muted",
          message.sender === "owner" && "rounded-br-sm bg-primary text-primary-foreground",
          (message.sender === "ai" || message.sender === "system") &&
            "rounded-br-sm border bg-background",
        )}
      >
        {message.body}
      </div>
      <span className="px-1 text-[0.65rem] text-muted-foreground">
        {c.senders[message.sender]} · {formatTime(message.created_at)}
      </span>
    </div>
  );
}
