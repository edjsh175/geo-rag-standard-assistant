import React, { createContext, useContext } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './answerMarkdown.css';

interface AnswerMarkdownProps {
  content: string;
}

const ListDepthContext = createContext(0);
const VISIBLE_LIST_ITEMS = 6;

const renderList = (
  tag: 'ul' | 'ol',
  children: React.ReactNode,
  className: string | undefined,
  start: number | undefined,
) => {
  const depth = useContext(ListDepthContext);
  const items = React.Children.toArray(children).filter(
    (child) => React.isValidElement(child) && child.type === 'li',
  );
  const ListTag = tag;
  const renderItems = (entries: React.ReactNode[], listStart?: number) => (
    <ListDepthContext.Provider value={depth + 1}>
      <ListTag className={className} start={listStart}>
        {entries}
      </ListTag>
    </ListDepthContext.Provider>
  );

  if (depth > 0 || items.length <= VISIBLE_LIST_ITEMS) {
    return renderItems(items, start);
  }

  const visibleItems = items.slice(0, VISIBLE_LIST_ITEMS);
  const hiddenItems = items.slice(VISIBLE_LIST_ITEMS);
  const continuationStart = tag === 'ol' ? (start ?? 1) + VISIBLE_LIST_ITEMS : undefined;

  return (
    <>
      {renderItems(visibleItems, start)}
      <details className="answer-markdown__list-disclosure">
        <summary>
          <span className="answer-markdown__expand-label">展开剩余 {hiddenItems.length} 项</span>
          <span className="answer-markdown__collapse-label">收起</span>
        </summary>
        {renderItems(hiddenItems, continuationStart)}
      </details>
    </>
  );
};

const markdownComponents: Components = {
  ul: ({ children, className }) => renderList('ul', children, className, undefined),
  ol: ({ children, className, node }) => {
    const start = typeof node?.properties?.start === 'number' ? node.properties.start : undefined;
    return renderList('ol', children, className, start);
  },
  table: ({ children }) => (
    <div className="answer-markdown__scroll-region" role="region" aria-label="可横向滚动的数据表格" tabIndex={0}>
      <table>{children}</table>
    </div>
  ),
  pre: ({ children }) => (
    <div className="answer-markdown__scroll-region answer-markdown__code-region" role="region" aria-label="可横向滚动的代码块" tabIndex={0}>
      <pre>{children}</pre>
    </div>
  ),
};

export const AnswerMarkdown: React.FC<AnswerMarkdownProps> = ({ content }) => (
  <div className="answer-markdown prose max-w-full">
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {content}
    </ReactMarkdown>
  </div>
);

export default AnswerMarkdown;
