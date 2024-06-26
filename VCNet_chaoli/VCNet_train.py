import os
from torchvision.utils import make_grid
from torch.utils.data import DataLoader
from torch.autograd import Variable
from torchvision import transforms
import time
import datetime
import tools
import numpy as np
import torch
# to draw loss
import matplotlib.pyplot as plt

# dim = (160, 224, 168)   # [depth, height, width]. brain
# dim = (96, 240, 384)    # [depth, height, width]. pelvic

# set path(for windows test)
# dataSourcePath = r"C:\Files\Research\dataSet2"
# dataSavePath = r"C:\Files\Research\VCNet\dataSave"

# set path(for macbook test)
dataSourcePath = "/Users/wanglikai/Codes/Volume_Complete/dataSet1"
dataSavePath = "/Users/wanglikai/Codes/Volume_Complete/VCNet/dataSave"

# set path(for linux Server)
# dataSourcePath = "/home/dell/storage/WANGLIKAI/dataSet/dataSet1"
# dataSavePath = "/home/dell/storage/WANGLIKAI/VCNet/output"

if not os.path.exists(f"{dataSavePath}/loss"):
        os.makedirs(f"{dataSavePath}/loss")

pthLoadPath = ""
# device=torch.device("cuda:0")
device=torch.device("cpu")

torch.autograd.set_detect_anomaly(True)

# print("pytorch version:",torch.__version__)  # 检查 PyTorch 版本
# print("cuda version:",torch.version.cuda)  # 检查 CUDA 版本
# print("cuda available:",torch.cuda.is_available())  # 检查是否可用 GPU
# print("available cuda number:",torch.cuda.device_count())  # 检查 GPU 数量
# print()

# clear cuda memory
torch.cuda.empty_cache()
torch.manual_seed(0)

# initialize weight of network
def weights_init(m):
    if isinstance(m, nn.Conv3d) or isinstance(m, nn.ConvTranspose3d):
        torch.nn.init.normal_(m.weight, 0.0, 0.02)
    if isinstance(m, nn.BatchNorm3d):
        torch.nn.init.normal_(m.weight, 0.0, 0.02)
        torch.nn.init.constant_(m.bias, 0)


#模型的代码实现见VCNet_model.py
from VCNet_model import *

# Feel free to change pretrained to False if you're training the model from scratch
pretrained = False
save_model = True

fileStartVal = 1
fileIncrement = 1
constVal = 1
total_gen_loss = []
total_disc_loss = []


#---------------------initialize the model----------------------
# 1) parameters for dataset
total_index = 100
ratio_for_train = 0.7
max_train_index = round(total_index*ratio_for_train)
# dim = (160, 224, 168)   # [depth, height, width]. brain
dim = (128, 128, 128)   # [depth, height, width]
float32DataType = np.float32

trainDataset = tools.DataSet(data_path=dataSourcePath,
                             volume_shape=dim,
                             mask_type="train",
                             prefix="original_volume_",
                             data_type="raw",
                             float32DataType=np.float32,
                             max_index=70)

# 2) other parameters
lambda_recon = 200
p_epochs = 400          # for pre train     # 预训练
f_epochs = 100          # for fine tune     # 微调
input_dim = 1
real_dim = 1
batch_size = 2          #原模型参数 10
lr = 5e-4             #learn rate 原模型参数 5e-3(0.005)
# lr = 1e-6
weight_decay_adv = 1e-4
weight_decay_rec = 1e-4
lambda_adv = 1e-3
lambda_rec = 1
test_mode = True
up_mode = 3

# display_step = np.ceil(np.ceil(max_train_index / batch_size) * n_epochs / 20)   #一共输出20个epoch，供判断用


# 3) send parameters to cuda
gen = UNet_v2(up_mode=up_mode).to(device)
gen_opt = torch.optim.Adam(gen.parameters(), lr=lr,betas=(0.9,0.999),weight_decay=weight_decay_rec)

disc = Dis_VCNet().to(device)
disc_opt = torch.optim.Adam(disc.parameters(), lr=lr,betas=(0.9,0.999),weight_decay=weight_decay_adv)

# 4) parameters for loss function
Loss_G_rec = tools.WeightedMSELoss().to(device)
# Loss_G_rec = nn.CrossEntropyLoss().to(device)
Loss_G_Adv = tools.AdversarialGLoss(disc).to(device)
Loss_D_Adv = tools.AdversarialDLoss(disc).to(device)

print("## initialize finished ##")

#---------------------------------training------------------------
if pretrained:
    loaded_state = torch.load(pthLoadPath)
    gen.load_state_dict(loaded_state["gen"])
    gen_opt.load_state_dict(loaded_state["gen_opt"])
    disc.load_state_dict(loaded_state["disc"])
    disc_opt.load_state_dict(loaded_state["disc_opt"])
else:
    gen = gen.apply(weights_init)
    disc = disc.apply(weights_init)
    
def pre_train(save_model=True,p_epochs=400):                          
    
    # read the start time
    ot = time.time()
    t1 = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print("## pre train start ##  time:",t1)
    
    # dataloader = DataLoader(trainDataset, batch_size=batch_size, shuffle=True, drop_last=True)
    dataloader = DataLoader(trainDataset, batch_size=batch_size, drop_last=True,pin_memory=True)
    print("    data loaded!")
    gen_opt.param_groups[0]['weight_decay'] = weight_decay_rec
    
    display_step = np.ceil(np.ceil(max_train_index / batch_size) * p_epochs / 20)   #一共输出20个epoch，供判断用
    cur_step = 0
    epoch_losses=[]
    
    for epoch in range(p_epochs):
        # if epoch == 1:
            # sys.exit()
        epoch_loss = []
        iter=0
        # Dataloader returns the batches
        # each iter
        for real_volume,masked_volume,mask,index in dataloader:
            
            # noise = np.random.normal(loc=0.5, scale=0.15, size=masked_volume.shape)
            # input_volume = masked_volume + mask*noise
            # input_volume = np.clip(input_volume,0.2,0.8)
            input_volume = input_volume.clone().detach().requires_grad_(True).float().to(device)
            
            # wrap them into torch.tensor
            real_volume = real_volume.clone().detach().requires_grad_(True).float().to(device)
            masked_volume = masked_volume.clone().detach().requires_grad_(True).float().to(device)
            mask = mask.clone().detach().requires_grad_(True).float().to(device)
            # print(mask.shape)
            
            output_volume = gen(input_volume,mask,
                                test_mode,
                                dataSavePath)
            
            real_volume_Variable = Variable(real_volume)
            masked_volume_Variable = Variable(masked_volume)
            output_volume_Variable = Variable(output_volume)
            
            gen_opt.zero_grad()  # Zero out the gradient before back propagation
            # update the generator only
            gen_loss = Loss_G_rec(real_volume_Variable.detach(),output_volume_Variable,mask)
            # gen_loss = Loss_G_rec(output_volume,real_volume.detach())
            if not gen_loss.requires_grad:
                gen_loss.clone().detach().requires_grad_(True)

            # print("    Weighted MSE Loss:", gen_loss.item())
            gen_loss.backward()
            gen_opt.step()
            epoch_loss.append(gen_loss.detach().item()) #每一个批次的损失
            
            
            ### save model and generated volume(if need) ###
            if (cur_step+1) % display_step == 0 or cur_step == 1:
                
                t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

                # compute time
                dt = time.time() - ot
                elapsedTime = str(datetime.timedelta(seconds=dt))
                per_epoch = str(datetime.timedelta(seconds=dt / (epoch+1)))
                print(f"    (save)")
                
                # save generated volume
                tools.saveRawFile10(f"{dataSavePath}/P_VCNet_{epoch}",
                                    f"vol_{cur_step:03d}_fake",
                                    output_volume[0, 0, :, :, :])
                
                tools.saveRawFile10(f"{dataSavePath}/P_VCNet_{epoch}",
                                    f"vol_{cur_step:03d}_true",
                                    real_volume[0, 0, :, :, :])

                tools.saveRawFile10(f"{dataSavePath}/P_VCNet_{epoch}",
                                    f"vol_{cur_step:03d}_masked",
                                    masked_volume[0, 0, :, :, :])

                # You can change save_model to True if you'd like to save the model
                if save_model:
                    fileName = f"{dataSavePath}/P_VCNet_{epoch}.pth"
                    torch.save({'gen': gen.state_dict(),
                                'gen_opt': gen_opt.state_dict(),
                                'disc': disc.state_dict(),
                                'disc_opt': disc_opt.state_dict(),
                                }, fileName)
                
            cur_step += 1
            iter += 1
            
        average_epoch_loss=sum(epoch_loss)/len(epoch_loss)
        epoch_losses.append(average_epoch_loss)
        
        # compute time
        dt = time.time() - ot
        elapsedTime = str(datetime.timedelta(seconds=dt))
        per_epoch = str(datetime.timedelta(seconds=dt / (epoch+1)))
        print(f"    Epoch = {epoch}/{p_epochs}     dt={elapsedTime}    per-epoch={per_epoch}    loss {average_epoch_loss:.4f}")
        
        plt.switch_backend('Agg')
        plt.figure()
        plt.plot(epoch_loss,'b',label = 'loss')
        plt.ylabel('loss')
        plt.xlabel('iter')
        plt.legend()        #个性化图例（颜色、形状等）
        plt.savefig(os.path.join(dataSavePath,f"loss/epoch{epoch}_loss.jpg")) #保存图片 路径：/imgPath/
        
        # draw loss
        plt.switch_backend('Agg')
        plt.figure()
        plt.plot(epoch_losses,'b',label = 'loss')
        plt.ylabel('loss')
        plt.xlabel('epoch')
        plt.legend()        #个性化图例（颜色、形状等）
        plt.savefig(os.path.join(dataSavePath,"loss/epoch_loss.jpg")) #保存图片 路径：/imgPath/


    t2 = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print("##train finished##  time:",t2)
    print("total train time:")
    print("start:",t1)
    print("end:",t2)
    
    
def fine_tune(save_model=True,f_epochs=100):
    # read the start time
    ot = time.time()
    t1 = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print("## fine tune start ##  time:",t1)
    
    # dataloader = DataLoader(trainDataset, batch_size=batch_size, shuffle=True, drop_last=True)
    dataloader = DataLoader(trainDataset, batch_size=batch_size, drop_last=True)
    print("    data loaded!")
    gen_opt.param_groups[0]['weight_decay'] = weight_decay_rec
    
    display_step = np.ceil(np.ceil(max_train_index / batch_size) * p_epochs / 20)   #一共输出20个epoch，供判断用
    cur_step = 0
    epoch_gen_losses=[]
    epoch_disc_losses=[]
    for epoch in range(f_epochs):
        epoch_gen_loss = []
        epoch_disc_loss = []
        iter=0
        # Dataloader returns the batches
        for real_volume,masked_volume,mask,index in dataloader:

            # wrap them into torch.tensor
            real_volume = real_volume.clone().detach().requires_grad_(True).float().to(device)
            masked_volume = masked_volume.clone().detach().requires_grad_(True).float().to(device)
            mask = mask.clone().detach().requires_grad_(True).float().to(device)
            
            output_volume = gen(masked_volume,
                                test_mode,
                                dataSavePath)
            
            real_volume_Variable = Variable(real_volume)
            masked_volume_Variable = Variable(masked_volume)
            output_volume_Variable = Variable(output_volume)
            
            # update disc
            disc_opt.zero_grad()  # Zero out the gradient before back propagation
            disc_loss = Loss_D_Adv(real_volume_Variable,output_volume_Variable,mask)
            # total_disc_loss.append(disc_loss)
            # print("Adv Disc Loss:", disc_loss.item())
            disc_loss.backward()
            disc_opt.step()
            epoch_disc_loss.append(disc_loss.detach().item()) #每一个批次的损失
            
            # update gen
            gen_opt.zero_grad()
            # print("update gen")
            gen_loss = lambda_adv*Loss_G_Adv(real_volume_Variable,output_volume_Variable,mask) + \
                       lambda_rec*Loss_G_rec(real_volume_Variable,output_volume_Variable,mask)
            # total_gen_loss.append(gen_loss)
            # print("Adv Gen Loss:", gen_loss.item())
            gen_loss.backward()
            gen_opt.step()
            epoch_gen_loss.append(gen_loss.detach().item())
            
            ## save model and generated volume(if need) ###
            if (cur_step+1) % display_step == 0 or cur_step == 2:
                print(f"    (save)")
                # save generated volume
                tools.saveRawFile10(f"{dataSavePath}/F_VCNet_{epoch}",
                                    f"vol_{cur_step:03d}_fake",
                                    output_volume[0, 0, :, :, :])

                tools.saveRawFile10(f"{dataSavePath}/F_VCNet_{epoch}",
                                    f"vol_{cur_step:03d}_true",
                                    real_volume[0, 0, :, :, :])

                tools.saveRawFile10(f"{dataSavePath}/F_VCNet_{epoch}",
                                    f"vol_{cur_step:03d}_masked",
                                    masked_volume[0, 0, :, :, :])

                # You can change save_model to True if you'd like to save the model
                if save_model:
                    fileName = f"{dataSavePath}/F_VCNet_{epoch}.pth"
                    torch.save({'gen': gen.state_dict(),
                                'gen_opt': gen_opt.state_dict(),
                                'disc': disc.state_dict(),
                                'disc_opt': disc_opt.state_dict(),
                                }, fileName)
                    
            cur_step += 1
            iter += 1

        average_gen_loss=sum(epoch_gen_loss)/len(epoch_gen_loss)
        average_disc_loss=sum(epoch_disc_loss)/len(epoch_disc_loss)
        epoch_gen_losses.append(average_gen_loss)
        epoch_disc_losses.append(average_disc_loss)
        
        # compute time
        dt = time.time() - ot
        elapsedTime = str(datetime.timedelta(seconds=dt))
        per_epoch = str(datetime.timedelta(seconds=dt / (epoch+1)))
        print(f"    Epoch = {epoch}/{f_epochs}     dt={elapsedTime}    per-epoch={per_epoch}    gen_loss={average_gen_loss:.4f}    disc_loss={average_disc_loss:.4f}")
        
        plt.switch_backend('Agg')
        plt.figure()
        plt.plot(epoch_gen_loss,'b',label = 'gen loss')
        plt.plot(epoch_disc_loss,'r',label = 'disc loss')
        plt.ylabel('loss')
        plt.xlabel('iter')
        plt.legend()        #个性化图例（颜色、形状等）
        plt.savefig(os.path.join(dataSavePath,f"loss/epoch{epoch}_loss.jpg")) #保存图片 路径：/imgPath/
        
        # draw loss
        plt.switch_backend('Agg')
        plt.figure()
        plt.plot(epoch_gen_losses,'b',label = 'loss')
        plt.plot(epoch_disc_losses,'r',label = 'disc loss')
        plt.ylabel('loss')
        plt.xlabel('epoch')
        plt.legend()        #个性化图例（颜色、形状等）
        plt.savefig(os.path.join(dataSavePath,"loss/epoch_losses.jpg")) #保存图片 路径：/imgPath/


    t2 = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print("##train finished##  time:",t2)
    print("total train time:")
    print("start:",t1)
    print("end:",t2)
            
# when to train? how to swift train mode???????
pre_train(True,800)
# fine_tune(True,200)