import {beforeEach,describe,expect,it,vi} from 'vitest';
const hooks=vi.hoisted(()=>({state:null as unknown,effect:null as null|(()=>void|(()=>void)),ref:{current:null as string|null}}));
vi.mock('react',()=>({useState:()=>[hooks.state,(v:unknown)=>{hooks.state=v;}],useEffect:(f:()=>void|(()=>void))=>{hooks.effect=f;},useRef:()=>hooks.ref}));
vi.mock('@/api/designApi',()=>({fetchUploadedImageContent:vi.fn()}));
import {fetchUploadedImageContent} from '@/api/designApi';
import {usePrivateImage} from './usePrivateImage';
describe('私有图片生命周期',()=>{
 beforeEach(()=>{hooks.state=null;hooks.ref.current=null;vi.clearAllMocks();vi.stubGlobal('URL',{createObjectURL:vi.fn(()=> 'blob:test'),revokeObjectURL:vi.fn()});});
 it('切回先前图片不能返回已撤销URL',async()=>{vi.mocked(fetchUploadedImageContent).mockResolvedValue(new Blob());usePrivateImage(1);const cleanup=hooks.effect!();await Promise.resolve();expect(usePrivateImage(1).url).toBe('blob:test');if(cleanup)cleanup();usePrivateImage(2);expect(usePrivateImage(1).url).toBeNull();expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');});
 it('终止后迟到Blob不能创建URL',async()=>{let resolve!:(b:Blob)=>void;vi.mocked(fetchUploadedImageContent).mockImplementation(()=>new Promise(r=>{resolve=r;}));usePrivateImage(1);const cleanup=hooks.effect!();if(cleanup)cleanup();resolve(new Blob());await Promise.resolve();expect(URL.createObjectURL).not.toHaveBeenCalled();expect(vi.mocked(fetchUploadedImageContent).mock.calls[0][1]?.aborted).toBe(true);});
});
