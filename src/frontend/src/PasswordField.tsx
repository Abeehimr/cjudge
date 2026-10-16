import { useId, useState, type InputHTMLAttributes } from 'react';

export default function PasswordField({ label = 'Password', className = '', ...props }:
  Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & { label?: string }) {
  const generatedId = useId(), id = props.id || generatedId;
  const [visible, setVisible] = useState(false);
  const action = `${visible ? 'Hide' : 'Show'} ${label.toLowerCase()}`;
  return <div className={className}>
    <label htmlFor={id}>{label}</label>
    <div className="relative mt-1">
      <input {...props} id={id} type={visible ? 'text' : 'password'} className="block w-full min-w-0 pr-10" />
      <button type="button" className="absolute inset-y-0 right-0 rounded-l-none border-0 px-2"
        disabled={props.disabled} aria-label={action} title={action} aria-controls={id} aria-pressed={visible}
        onClick={() => setVisible((old) => !old)}>
        <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
          <circle cx="12" cy="12" r="3" />
          {visible && <path d="m3 3 18 18" />}
        </svg>
      </button>
    </div>
  </div>;
}
